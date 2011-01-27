#! /usr/bin/env python
"""
"""

#Init has to be imported first because it has code to workaround the python bug where relative imports don't work if the module is imported as a main module.
import __init__

from datetime import date
from fabmetheus_utilities.fabmetheus_tools import fabmetheus_interpret
from fabmetheus_utilities import archive
from fabmetheus_utilities import euclidean
from fabmetheus_utilities import gcodec
from fabmetheus_utilities import intercircle
from fabmetheus_utilities import settings
from skeinforge_application.skeinforge_utilities import skeinforge_craft
from skeinforge_application.skeinforge_utilities import skeinforge_polyfile
from skeinforge_application.skeinforge_utilities import skeinforge_profile
import math
import os
import sys


__author__ = 'Enrique Perez (perez_enrique@yahoo.com)'
__date__ = "$Date: 2008/28/04 $"
__license__ = 'GPL 3.0'


def getCraftedText( fileName, gcodeText = '', repository=None):
	"Volumetric 5D a gcode file or text."
	return getCraftedTextFromText( archive.getTextIfEmpty(fileName, gcodeText), repository )

def getCraftedTextFromText(gcodeText, repository=None):
	"Volumetric 5D a gcode text."
	if gcodec.isProcedureDoneOrFileIsEmpty( gcodeText, 'volumetric'):
		return gcodeText
	if repository == None:
		repository = settings.getReadRepository( VolumetricRepository() )
	if not repository.activateVolumetric.value:
		return gcodeText
	return VolumetricSkein().getCraftedGcode(gcodeText, repository)

def getNewRepository():
	"Get the repository constructor."
	return VolumetricRepository()

def writeOutput(fileName=''):
	"Volumetric 5D a gcode file."
	fileName = fabmetheus_interpret.getFirstTranslatorFileNameUnmodified(fileName)
	if fileName != '':
		skeinforge_craft.writeChainTextWithNounMessage( fileName, 'volumetric')


class VolumetricRepository:
	"A class to handle the volumetric settings."
	def __init__(self):
		"Set the default settings, execute title & settings fileName."
		skeinforge_profile.addListsToCraftTypeRepository('skeinforge_application.skeinforge_plugins.craft_plugins.volumetric.html', self )
		self.fileNameInput = settings.FileNameInput().getFromFileName( fabmetheus_interpret.getGNUTranslatorGcodeFileTypeTuples(), 'Open File for Volumetric', self, '')
		self.openWikiManualHelpPage = settings.HelpPage().getOpenFromAbsolute('http://www.bitsfrombytes.com/wiki/index.php?title=Skeinforge_Volumetric')
		self.activateVolumetric = settings.BooleanSetting().getFromValue('Activate Volumetric', self, False )
		extrusionDistanceFormatLatentStringVar = settings.LatentStringVar()
		self.extrusionDistanceFormatChoiceLabel = settings.LabelDisplay().getFromName('Extrusion Distance Format Choice: ', self )
		settings.Radio().getFromRadio( extrusionDistanceFormatLatentStringVar, 'Absolute Extrusion Distance', self, True )
		self.relativeExtrusionDistance = settings.Radio().getFromRadio( extrusionDistanceFormatLatentStringVar, 'Relative Extrusion Distance', self, False )
		self.extruderRetractionSpeed = settings.FloatSpin().getFromValue( 4.0, 'Extruder Retraction Speed (mm/s):', self, 34.0, 13.3 )
		self.retractionDistance = settings.FloatSpin().getFromValue( 0.0, 'Retraction Distance (millimeters):', self, 100.0, 0.0 )
		self.restartExtraDistance = settings.FloatSpin().getFromValue( 0.0, 'Restart Extra Distance (millimeters):', self, 100.0, 0.0 )
		settings.LabelSeparator().getFromRepository(self)
		settings.LabelDisplay().getFromName('- Filament Details -', self )
		self.filamentWidth = settings.FloatSpin().getFromValue( 0, 'Filament Width (mm):', self, 6, 2.8 )
		self.filamentContraction = settings.FloatSpin().getFromValue( -3, 'Filament Contraction (ratio out/in):', self, 3, 0.85 )
		self.executeTitle = 'Volumetric'

	def execute(self):
		"Volumetric button has been clicked."
		fileNames = skeinforge_polyfile.getFileOrDirectoryTypesUnmodifiedGcode(self.fileNameInput.value, fabmetheus_interpret.getImportPluginFileNames(), self.fileNameInput.wasCancelled)
		for fileName in fileNames:
			writeOutput(fileName)


class VolumetricSkein:
	"A class to volumetric a skein of extrusions."
	def __init__(self):
		self.absoluteDistanceMode = True
		self.distanceFeedRate = gcodec.DistanceFeedRate()
		self.feedRateMinute = None
		self.isExtruderActive = False
		self.lineIndex = 0
		self.oldLocation = None
		self.operatingFlowRate = None
		self.totalExtrusionDistance = 0.0
		self.layerThickness = 0.0
		self.perimeterWidth = 0.0
		self.feedScale = 1.0
		self.retractionLeft = 0.0

	def addLinearMoveExtrusionDistanceLine( self, extrusionDistance ):
		"Get the extrusion distance string from the extrusion distance."
		self.distanceFeedRate.output.write('G1 F%s\n' % self.extruderRetractionSpeedMinuteString )
		self.distanceFeedRate.output.write('G1%s\n' % self.getExtrusionDistanceStringFromExtrusionDistance( extrusionDistance ) )
		self.distanceFeedRate.output.write('G1 F%s\n' % self.distanceFeedRate.getRounded( self.feedRateMinute ) )

	def getCraftedGcode(self, gcodeText, repository):
		"Parse gcode text and store the volumetric gcode."
		self.repository = repository
		self.lines = archive.getTextLines(gcodeText)
		self.parseInitialization()
		if self.operatingFlowRate == None:
			print('There is no operatingFlowRate so volumetric will do nothing.')
			return gcodeText
		self.restartDistance = self.repository.retractionDistance.value + self.repository.restartExtraDistance.value
		self.extruderRetractionSpeedMinuteString = self.distanceFeedRate.getRounded( 60.0 * self.repository.extruderRetractionSpeed.value )
		for lineIndex in xrange( self.lineIndex, len(self.lines) ):
			self.parseLine( lineIndex )
		return self.distanceFeedRate.output.getvalue()

	def getVolumetricedArcMovement(self, line, splitLine):
		"Get a volumetriced arc movement."
		if self.oldLocation == None:
			return line
		relativeLocation = gcodec.getLocationFromSplitLine(self.oldLocation, splitLine)
		self.oldLocation += relativeLocation
		distance = gcodec.getArcDistance(relativeLocation, splitLine)
		return line + self.getExtrusionDistanceString(distance, splitLine)

	def getVolumetricedLinearMovement( self, line, splitLine ):
		"Get a volumetriced linear movement."
		distance = 0.0
		if self.absoluteDistanceMode:
			location = gcodec.getLocationFromSplitLine(self.oldLocation, splitLine)
			if self.oldLocation != None:
				distance = abs( location - self.oldLocation )
			self.oldLocation = location
		else:
			if self.oldLocation == None:
				print('Warning: There was no absolute location when the G91 command was parsed, so the absolute location will be set to the origin.')
				self.oldLocation = Vector3()
			location = gcodec.getLocationFromSplitLine(None, splitLine)
			distance = abs( location )
			self.oldLocation += location
		return line + self.getExtrusionDistanceString( distance, splitLine )

	def getExtrusionDistanceString( self, distance, splitLine ):
		"Get the extrusion distance string."
		self.feedRateMinute = gcodec.getFeedRateMinute( self.feedRateMinute, splitLine )
		if not self.isExtruderActive:
			return ''
		if distance <= 0.0:
			return ''
		return self.getExtrusionDistanceStringFromExtrusionDistance( self.flowRate * self.feedScale * distance )

	def getExtrusionDistanceStringFromExtrusionDistance( self, extrusionDistance ):
		"Get the extrusion distance string from the extrusion distance."
		if self.repository.relativeExtrusionDistance.value:
			return ' E' + self.distanceFeedRate.getRounded( extrusionDistance )
		self.totalExtrusionDistance += extrusionDistance
		return ' E' + self.distanceFeedRate.getRounded( self.totalExtrusionDistance )

	def parseInitialization(self):
		'Parse gcode initialization and store the parameters.'
		for self.lineIndex in xrange(len(self.lines)):
			line = self.lines[self.lineIndex]
			splitLine = gcodec.getSplitLineBeforeBracketSemicolon(line)
			firstWord = gcodec.getFirstWord(splitLine)
			self.distanceFeedRate.parseSplitLine(firstWord, splitLine)
			if firstWord == '(</extruderInitialization>)':
				self.distanceFeedRate.addLine('(<procedureDone> volumetric </procedureDone>)')
				self.feedScale = (self.layerThickness * self.perimeterWidth) / (math.pi * ((self.repository.filamentWidth.value / 2) * (self.repository.filamentWidth.value / 2)) * self.repository.filamentContraction.value)
				return
			elif firstWord == '(<operatingFeedRatePerSecond>':
				self.feedRateMinute = 60.0 * float(splitLine[1])
			elif firstWord == '(<operatingFlowRate>':
				self.operatingFlowRate = float(splitLine[1])
				self.flowRate = self.operatingFlowRate
			elif firstWord == '(<layerThickness>':
				self.layerThickness = float(splitLine[1])
			elif firstWord == '(<perimeterWidth>':
				self.perimeterWidth = float(splitLine[1])
				self.feedScale = (self.layerThickness * self.perimeterWidth) / (math.pi * ((self.repository.filamentWidth.value / 2) * (self.repository.filamentWidth.value / 2)) * self.repository.filamentContraction.value)
				self.distanceFeedRate.addLine('(<feedrateScale> %s </feedrateScale>)' % self.distanceFeedRate.getRounded(self.feedScale))
			self.distanceFeedRate.addLine(line)

	def parseLine( self, lineIndex ):
		"Parse a gcode line and add it to the volumetric skein."
		line = self.lines[lineIndex].lstrip()
		splitLine = line.split()
		if len(splitLine) < 1:
			return
		firstWord = splitLine[0]
		if firstWord == 'G2' or firstWord == 'G3':
			line = self.getVolumetricedArcMovement( line, splitLine )
		if firstWord == 'G1':
			line = self.getVolumetricedLinearMovement( line, splitLine )
		if firstWord == 'G90':
			self.absoluteDistanceMode = True
		elif firstWord == 'G91':
			self.absoluteDistanceMode = False
		elif firstWord == 'M101':
			self.addLinearMoveExtrusionDistanceLine( self.restartDistance )
			if not self.repository.relativeExtrusionDistance.value:
				self.distanceFeedRate.addLine('G92 E0')
				self.totalExtrusionDistance = 0.0
			self.isExtruderActive = True
			return
		elif firstWord == 'M103':
			self.addLinearMoveExtrusionDistanceLine( - self.repository.retractionDistance.value )
			self.isExtruderActive = False
			return
		elif firstWord == 'M108':
			self.flowRate = float( splitLine[1][1 :] )
			return
		self.distanceFeedRate.addLine(line)


def main():
	"Display the volumetric dialog."
	if len(sys.argv) > 1:
		writeOutput(' '.join(sys.argv[1 :]))
	else:
		settings.startMainLoopFromConstructor( getNewRepository() )

if __name__ == "__main__":
	main()
