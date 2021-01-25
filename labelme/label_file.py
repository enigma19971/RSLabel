import base64
import json
import os.path

from . import logger
from . import utils


class LabelFileError(Exception):
	pass


class LabelFile(object):

	suffix = '.json'

	def __init__(self, filename=None,mode = 'train'):
		self.shapes = ()
		self.imagePath = None
		self.imageData = None
		self.filename = filename
		if filename is not None:
			try:
				if(mode=='train'):
					self.loadTrain(filename)
				else:
					self.loadInfer(filename)
			except Exception as e:
				print(e)

	def loadInfer(self, filename):
		self.imagePath = filename
		self.otherData = {}
		self.flags = None
		try:
			with open(filename,'r',encoding='utf-8') as f:
				ret_dic = json.load(f)
				slice = ret_dict('slice')
				data = {}
				self.fillColor = [0,0,0,255]
				self.lineColor = [0,0,0,255]
				self.otherData['geotrans'] = ret_dict['geoTrans']
				shapes = []
				for box in slice:
					s = {}
					s['label']= box['class_id']
					lu_lon = box['lu_lon']
					lu_lat = box['lu_lat']
					rd_lon = box['rd_lon']
					rd_lat = box['rd_lat']
					s['points'] = [[lu_lon,lu_lat],[rd_lon,rd_lat]]
					s['fill_color'] = self.fillColor
					s['line_color'] = self.lineColor
					s['shape_type']= 'rectangle'
					s['probability'] = 1
					shapes.append(s)
				data['shapes'] = shapes
				self.shapes = shapes
		except Exception as e:
			print(e)
			raise LabelFileError(e)

	def loadTrain(self, filename):
		keys = [
			'imageData',
			'imagePath',
			'lineColor',
			'fillColor',
			'shapes',  # polygonal annotations
			'flags',   # image level flags
			'imageHeight',
			'imageWidth',
		]
		try:
			with open(filename, 'r') as f:
				data = json.load(f)
			if data['imageData'] is not None:
				imageData = base64.b64decode(data['imageData'])
			else:
				# relative path from label file to relative path from cwd
				imagePath = os.path.join(os.path.dirname(filename),
										 data['imagePath'])
				with open(imagePath, 'rb') as f:
					imageData = f.read()
			flags = data.get('flags')
			imagePath = data['imagePath']
			lineColor = data['lineColor']
			fillColor = data['fillColor']
			shapes = (
				(
					s['label'],
					s['points'],
					s['line_color'],
					s['fill_color'],
					s.get('shape_type', 'polygon'),
					s['probability'],
				)
				for s in data['shapes']
			)
		except Exception as e:
			raise LabelFileError(e)

		otherData = {}
		for key, value in data.items():
			if key not in keys:
				otherData[key] = value

		# Only replace data after everything is loaded.
		self.flags = flags
		self.shapes = shapes
		self.imagePath = imagePath
		self.imageData = imageData
		self.lineColor = lineColor
		self.fillColor = fillColor
		self.filename = filename
		self.otherData = otherData

	@staticmethod
	def _check_image_height_and_width(imageData, imageHeight, imageWidth):
		img_arr = utils.img_b64_to_arr(imageData)
		if imageHeight is not None and img_arr.shape[0] != imageHeight:
			logger.error(
				'imageHeight does not match with imageData or imagePath, '
				'so getting imageHeight from actual image.'
			)
			imageHeight = img_arr.shape[0]
		if imageWidth is not None and img_arr.shape[1] != imageWidth:
			logger.error(
				'imageWidth does not match with imageData or imagePath, '
				'so getting imageWidth from actual image.'
			)
			imageWidth = img_arr.shape[1]
		return imageHeight, imageWidth

	def save(
		self,
		filename,
		shapes,
		imagePath,
		imageHeight,
		imageWidth,
		imageData=None,
		lineColor=None,
		fillColor=None,
		otherData=None,
		flags=None,
	):
		'''
		if imageData is not None:
			imageData = base64.b64encode(imageData).decode('utf-8')
			imageHeight, imageWidth = self._check_image_height_and_width(
				imageData, imageHeight, imageWidth
			)
		'''
		if otherData is None:
			otherData = {}
		if flags is None:
			flags = {}
		data = dict(
			version=1,
			flags=flags,
			shapes=shapes,
			lineColor=lineColor,
			fillColor=fillColor,
			imagePath=imagePath,
			imageData=imageData,
			imageHeight=imageHeight,
			imageWidth=imageWidth,
		)
		for key, value in otherData.items():
			data[key] = value
		try:
			with open(filename, 'w') as f:
				json.dump(data, f, ensure_ascii=False, indent=2)
			self.filename = filename
		except Exception as e:
			raise LabelFileError(e)

	@staticmethod
	def isLabelFile(filename):
		return os.path.splitext(filename)[1].lower() == LabelFile.suffix
