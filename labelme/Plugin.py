from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.uic import loadUi
from .label_dialog import *
from .tool_bar import *
from .label_file import *
from .labelme2COCO import *
from .label_qlist_widget import *
from .escapable_qlist_widget import *
from .utils import struct
from .utils import addActions
from .utils import fmtShortcut
from .utils import newAction
from .utils import newIcon
from .color_dialog import *
import webbrowser
import glob 
import shutil
import copy
import functools
import lxml.builder
import lxml.etree
import os.path as osp
import yaml
import gdal
import math
from . import get_config
from rslabel.gui import qtMouseListener
from rslabel.gui import LabelmeEditor
from rslabel.gui import LabelmeShape  

__appname__ = 'RSLabel'


DEFAULT_LINE_COLOR = QtGui.QColor(0, 255, 0, 128)
DEFAULT_FILL_COLOR = QtGui.QColor(255, 0, 0, 128)
DEFAULT_SELECT_LINE_COLOR = QtGui.QColor(255, 255, 255)
DEFAULT_SELECT_FILL_COLOR = QtGui.QColor(0, 128, 255, 155)
DEFAULT_VERTEX_FILL_COLOR = QtGui.QColor(0, 255, 0, 255)
DEFAULT_HVERTEX_FILL_COLOR = QtGui.QColor(255, 0, 0)


here = os.path.dirname(os.path.realpath(__file__))

class LabelmePlugin:
    def __init__(self, iface):
        gdal.AllRegister()
        self.iface=iface
        self.mainWnd = self.iface.mainWindow()
        self.canvas = iface.canvas()
        self.editor = iface.editor()
        self.menuBar = self.mainWnd.menuBar()
        self.fileInfo_dock = self.iface.getInfoWidget()
        self.fileInfo_dock.setVisible(False)
        config = get_config()
        self._config = config
        self.colorDialog = ColorDialog(parent=self.mainWnd)
        self.grid_color = None
        self.grid_size = None 
        self.shortName = False 
        self.labelFile = None

        # Whether we need to save or not.
        self.dirty = False
        self.filename = None
        self.output_file = None
        self.output_dir = None
        self.supportedFmts = ['img','tif','tiff','png', 'jpg', 'ecw', 'gta', 'pix']
        self._noSelectionSlot = False
        self.imageWidth = 0
        self.imageHeight = 0



    def initGui(self):
        """Function initalizes GUI of the OSM Plugin.
        """
        print('* init Gui')
        self.dockWidgetVisible = False

        #mouse listener
        self.mouseListener = qtMouseListener()
        self.mouseListener.onMouseRelease = self.mouseRelease
        self.iface.addMouseListener(self.mouseListener)
   
        #Context Menus and cursor:
        self.canvasMenus = (QtWidgets.QMenu(), QtWidgets.QMenu())   
        
     
        # Main widgets and related state.
        self.labelDialog = LabelDialog(
            parent=self.mainWnd,
            labels=self._config['labels'],
            sort_labels=self._config['sort_labels'],
            show_text_field=self._config['show_label_text_field'],
            completion=self._config['label_completion'],
            fit_to_content=self._config['fit_to_content'],
        )
        #config and settings       
        # XXX: Could be completely declarative.
        # Restore application settings.
        self.settings = QtCore.QSettings('labelme', 'labelme')
        # FIXME: QSettings.value can return None on PyQt4

        self.recentFiles = self.settings.value('recentFiles', []) or []
        self.createDockWidgets()        
        self.createActionsAndMenus()
        #add tool bar to main window
        self.tools = self.toolbar('Tools')
        self.populateModeActions()
        self.setSignals()
     
        # Application state.
        self.image = QtGui.QImage()
        self.imagePath = None
        self.recentFiles = []
        self.maxRecent = 7
        self.lineColor = DEFAULT_LINE_COLOR 
        self.fillColor = DEFAULT_FILL_COLOR
        self.otherData = {} 
       
        #set grid size
        self.grid_size = self.settings.value('grid_size')
        if(self.grid_size is not None):
            print('* load grid size configure')
            self.iface.setGridSize(int(self.grid_size))

        # Populate the File menu dynamically.
        self.updateFileMenu()
        # Since loading the file may take some time,
        # make sure it runs in the background.
        if self.filename is not None:
            self.queueEvent(functools.partial(self.loadFile, self.filename))
        
        self.statusBar().showMessage('%s started.' % __appname__)
        self.statusBar().show()
      
    def fileSearchChanged(self):
        self.importDirImages(
            self.lastOpenDir,
            pattern=self.fileSearch.text(),
            load=False,
        )

    # Message Dialogs. #
    def hasLabels(self):
        if not self.labelList.itemsToShapes:
            self.errorMessage(
                'No objects labeled',
                'You must label at least one object to save the file.')
            return False
        return True

    def mayContinue(self):
        if not self.dirty:
            return True
        mb = QtWidgets.QMessageBox
        msg = '在关闭之前将标记保存到"{}" ?'.format(self.filename)
        answer = mb.question(self.mainWnd,
                             '保存标记?',
                             msg,
                             mb.Save | mb.Discard | mb.Cancel,
                             mb.Save)
        if answer == mb.Discard:
            return True
        elif answer == mb.Save:
            self.saveFile()
            return True
        else:  # answer == mb.Cancel
            return False

    def fileSelectionChanged(self):
        items = self.fileListWidget.selectedItems()
        if not items:
            return
        item = items[0]

        if not self.mayContinue():
            return

        if(self.shortName):
            filename = self.short_long_name[str(item.text())]
            currIndex = self.imageList.index(filename)
        else:
            currIndex = self.imageList.index(str(item.text()))

        if currIndex < len(self.imageList):
            filename = self.imageList[currIndex]
            if filename:
                self.loadFile(filename)


    def setDirty(self):
        if self._config['auto_save'] or self.actions.saveAuto.isChecked():
            label_file = osp.splitext(self.imagePath)[0] + '.json'
            if self.output_dir:
                label_file = osp.join(self.output_dir, label_file)
            self.saveLabels(label_file)
            return
        self.dirty = True
        self.actions.save.setEnabled(True)
        self.actions.undo.setEnabled(self.editor.isShapeRestorable())
        title = __appname__
        if self.filename is not None:
            title = '{} - {}*'.format(title, self.filename)
        self.mainWnd.setWindowTitle(title)
        print('* set dirty')
        

    # Callback functions:
    def newShape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        items = self.uniqLabelList.selectedItems()
        text = None
        if items:
            text = items[0].text()
        if self._config['display_label_popup'] or not text:
            result = self.labelDialog.popUp(text, 10)
        if result is None:
            return
        text , prob = result
        if text is not None and not self.validateLabel(text):
            self.errorMessage('无效的标签',
                              "Invalid label '{}' with validation type '{}'"
                              .format(text, self._config['validate_label']))
            text = None
        if text is None:
            self.editor.undoLastLine()
            #self.editor.shapesBackups.pop()
        else:
            shape = self.editor.setLastLabel(text)
            shape.setProbability(prob)
            self.addLabel(shape)
            self.editor.commit()
            self.actions.editMode.setEnabled(True)
            self.actions.undoLastPoint.setEnabled(False)
            self.actions.undo.setEnabled(True)
            self.setDirty()

    def  editLabel(self, item=None):
        print('*editLabel')
        if (not self.editor.isEditing()) and (not self.editor.canBreak()):
            print('*editLabel, not editing. return')
            return
        item = item if item else self.currentItem()
        shape = self.labelList.get_shape_from_item(item)
        result = self.labelDialog.popUp(item.text(),shape.getProbability())
        if result is None:
            return
        text , prob = result
        if not self.validateLabel(text):
            self.errorMessage('Invalid label',
                              "Invalid label '{}' with validation type '{}'"
                              .format(text, self._config['validate_label']))
            return
        item.setText(text)
        shape.setProbability(prob)
        self.setDirty()
        if not self.uniqLabelList.findItems(text, Qt.MatchExactly):
            self.uniqLabelList.addItem(text)
            self.uniqLabelList.sortItems()


    # React to canvas signals.
    def shapeSelectionChanged(self, selected=False):
        print('* shapeSelectionChanged slot triggered')
        if self._noSelectionSlot:
            self._noSelectionSlot = False
        else:
            shape = self.editor.selectedShape()
            if shape:
                item = self.labelList.get_item_from_shape(shape)
                item.setSelected(True)
            else:
                self.labelList.clearSelection()
        self.actions.delete.setEnabled(selected)
        self.actions.copy.setEnabled(selected)
        self.actions.edit.setEnabled(selected)
        self.actions.shapeLineColor.setEnabled(selected)
        self.actions.shapeFillColor.setEnabled(selected)

    def addLabel(self, shape):
        item = QtWidgets.QListWidgetItem(shape.getLabel())
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.labelList.itemsToShapes.append((item, shape))
        self.labelList.addItem(item)
        if not self.uniqLabelList.findItems(shape.getLabel(), Qt.MatchExactly):
            self.uniqLabelList.addItem(shape.getLabel())
            self.uniqLabelList.sortItems()
        self.labelDialog.addLabelHistory(item.text())
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)

    def noShapes(self):
        return not self.labelList.itemsToShapes

    def remLabel(self, shape):
        item = self.labelList.get_item_from_shape(shape)
        self.labelList.takeItem(self.labelList.row(item))

    def loadShapes(self, shapes):
        for shape in shapes:
            self.addLabel(shape)
        self.editor.loadShapes(shapes)

    def loadLabels(self, shapes):
        s = []
        for label, points, line_color, fill_color, shape_type, probability in shapes:
            shape = LabelmeShape(label, shape_type)
            shape.setProbability(probability)
            for x, y in points:
                print('*({},{})'.format(x,y))
                shape.addPoint(QtCore.QPointF(x, y))
            shape.close()
            s.append(shape)
            if line_color:
                shape.line_color = QtGui.QColor(*line_color)
            if fill_color:
                shape.fill_color = QtGui.QColor(*fill_color)
        self.loadShapes(s)

    #*
    def loadFlags(self, flags):
        print('*load Flags', flags)
        self.flag_widget.clear()
        for key, flag in flags.items():
            item = QtWidgets.QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if flag else Qt.Unchecked)
            self.flag_widget.addItem(item)


    # called by saveFile
    def saveLabels(self, filename):
        lf = LabelFile()
        def format_shape(s):
            print('*',len(s.thePoints))
            return dict(
                label= s.getLabel(),
                line_color=s.line_color.getRgb()
                if s.line_color != self.lineColor else None,
                fill_color=s.fill_color.getRgb()
                if s.fill_color != self.fillColor else None,
                points=[(p.x(), p.y()) for p in s.thePoints],
                probability = s.getProbability(),
                shape_type=s.getType(),
            )

        shapes = [format_shape(shape) for shape in self.labelList.shapes]
        flags = {}
        for i in range(self.flag_widget.count()):
            item = self.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.Checked
            flags[key] = flag
        try:
            imagePath = osp.relpath(
                self.imagePath, osp.dirname(filename))
            imageData = self.imageData if self._config['store_data'] else None
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))
            lf.save(
                filename=filename,
                shapes=shapes,
                imagePath=imagePath,
                imageData=imageData,
                imageHeight=self.imageHeight,
                imageWidth=self.imageWidth,
                lineColor=self.lineColor.getRgb(),
                fillColor=self.fillColor.getRgb(),
                otherData=self.otherData,
                flags=flags,
            )
            print('* save label, imageWidth is {}'.format(self.imageWidth))
            self.labelFile = lf
            items = self.fileListWidget.findItems(
                self.imagePath, Qt.MatchExactly
            )
            if len(items) > 0:
                if len(items) != 1:
                    raise RuntimeError('There are duplicate files.')
                items[0].setCheckState(Qt.Checked)
            # disable allows next and previous image to proceed
            # self.filename = filename
            return True
        except LabelFileError as e:
            self.errorMessage('Error saving label data', '<b>%s</b>' % e)
            return False


    def importDirImages(self, dirpath, pattern=None, load=True):
        self.actions.openNextImg.setEnabled(True)
        self.actions.openPrevImg.setEnabled(True)

        if not self.mayContinue() or not dirpath:
            return

        self.lastOpenDir = dirpath
        self.filename = None
        self.fileListWidget.clear()
        self.short_long_name = {}
        for filename in self.scanAllImages(dirpath):
            if pattern and pattern not in filename:
                continue
            filename = filename.replace('\\','/')
            label_file = osp.splitext(filename)[0] + '.json'
            if self.output_dir:
                label_file = osp.join(self.output_dir, label_file)
            self.short_long_name[osp.basename(filename)] = filename
            if(self.shortName):
                item = QtWidgets.QListWidgetItem(osp.basename(filename))
            else:
                item = QtWidgets.QListWidgetItem(filename)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if QtCore.QFile.exists(label_file) and \
                    LabelFile.isLabelFile(label_file):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.fileListWidget.addItem(item)
        self.openNextImg(load=load)

    def undoShapeEdit(self):
        self.canvas.restoreShape()
        self.labelList.clear()
        self.loadShapes(self.canvas.shapes)
        self.actions.undo.setEnabled(self.canvas.isShapeRestorable)

    def togglePolygons(self, value):
        for item, shape in self.labelList.itemsToShapes:
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def importOfflineTileLayer(self, name):
        self.iface.importOfflineXYZtiles(self.offlineImportDir,name)

    def openDirDialog(self, _value=False, dirpath=None):
        if not self.mayContinue():
            return
        self.lastOpenDir = self.settings.value('lastOpenDir')
        defaultOpenDirPath = dirpath if dirpath else '.'
        if self.lastOpenDir and osp.exists(self.lastOpenDir):
            defaultOpenDirPath = self.lastOpenDir
        else:
            defaultOpenDirPath = osp.dirname(self.filename) \
                if self.filename else '.'

        targetDirPath = str(QtWidgets.QFileDialog.getExistingDirectory(
            self.mainWnd, '%s - Open Directory' % __appname__, defaultOpenDirPath,
            QtWidgets.QFileDialog.ShowDirsOnly |
            QtWidgets.QFileDialog.DontResolveSymlinks))
        self.importDirImages(targetDirPath)
        self.actions.exportAs.setEnabled(True)
        self.lastOpenDir = targetDirPath
        self.settings.setValue('lastOpenDir', self.lastOpenDir)
        self.settings.sync()

    def openFile(self, _value=False):
        if not self.mayContinue():
            return
        lastOpenDir = self.settings.value('lastOpenDir')
        path = osp.dirname(str(self.filename)) if self.filename else lastOpenDir 
        formats = ['*.tif', '*.jpg', '*.tiff', '*.pix', '*.pci', '*.img']
        filters = "Image & Label files (%s)" % ' '.join(
            formats + ['*%s' % LabelFile.suffix])
        filename = QtWidgets.QFileDialog.getOpenFileName(
            self.mainWnd, '%s - Choose Image or Label file' % __appname__,
            path, filters)
        filename, _ = filename
        filename = str(filename)
        if filename:
            self.loadFile(filename)
            basename = osp.splitext(filename)[0]
            self.settings.setValue('lastOpenDir', basename)


    def openPrevImg(self, _value=False):
        keep_prev = self._config['keep_prev']
        if QtGui.QGuiApplication.keyboardModifiers() == \
                (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier):
            self._config['keep_prev'] = True
        if not self.mayContinue():
            return
        if len(self.imageList) <= 0:
            return
        if self.filename is None:
            return
        currIndex = self.imageList.index(self.filename)
        if currIndex - 1 >= 0:
            filename = self.imageList[currIndex - 1]
            if filename:
                self.loadFile(filename)
        self._config['keep_prev'] = keep_prev


    def openNextImg(self, _value=False, load=True):
        keep_prev = self._config['keep_prev']
        if QtGui.QGuiApplication.keyboardModifiers() == \
                (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier):
            self._config['keep_prev'] = True
        if not self.mayContinue():
            return
        if len(self.imageList) <= 0:
            return
        filename = None
        if self.filename is None:
            filename = self.imageList[0]
        else:
            currIndex = self.imageList.index(self.filename)
            if currIndex + 1 < len(self.imageList):
                filename = self.imageList[currIndex + 1]
            else:
                filename = self.imageList[-1]
        self.filename = filename
        if self.filename and load:
            self.loadFile(self.filename)
        self._config['keep_prev'] = keep_prev

    def saveFile(self, _value=False):
        if self._config['flags'] or self.hasLabels():
            print('*save File')
            if self.labelFile:
                # DL20180323 - overwrite when in directory
                self._saveFile(self.labelFile.filename)
            elif self.output_file:
                print('[python] <saveFile> has output file',self.output_file)
                self._saveFile(self.output_file)
                self.close()
            else:
                print('[python] <saveFile> call _saveFile')
                self._saveFile(self.saveFileDialog())

    #add toolbar the main window
    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName('%sToolBar' % title)
        # toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        if actions:
            addActions(toolbar, actions)
        self.iface.addToolbar(toolbar)
        return toolbar

    #add menu to main window
    def menu(self, title, actions=None):
        menu = self.menuBar.addMenu(title)
        if actions:
            addActions(menu, actions)
        return menu

    def populateModeActions(self):
        tool, menu = self.actions.tool, self.actions.menu
        self.tools.clear()
        addActions(self.tools, tool)
        # self.canvasMenus[0].clear() *why clear here? 
        # addActions(self.iface.canvas(), menu)
        self.menus.edit.clear()
        actions = (
            self.actions.createMode,
            self.actions.createRectangleMode,
            self.actions.createCircleMode,
            self.actions.createLineMode,
            self.actions.createSlantRectMode,
            self.actions.createLineStripMode,
            self.actions.editMode,
        )
        addActions(self.menus.edit, actions + self.actions.editMenu) 

    def saveFileAs(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        if self.hasLabels():
            self._saveFile(self.saveFileDialog())

    def currentPath(self):
        return osp.dirname(str(self.filename)) if self.filename else '.'

    def saveFileDialog(self):
        caption = '%s - Choose File' % __appname__
        filters = 'Label files (*%s)' % LabelFile.suffix
        if self.output_dir:
            dlg = QtWidgets.QFileDialog(
                self, caption, self.output_dir, filters
            )
        else:
            dlg = QtWidgets.QFileDialog(
                self.mainWnd, caption, self.currentPath(), filters
            )
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dlg.setOption(QtWidgets.QFileDialog.DontConfirmOverwrite, False)
        dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, False)
        print('[python]: <saveFileDialog> self.filename is ' ,self.filename)
        basename = osp.splitext(self.filename)[0]
        if self.output_dir:
            default_labelfile_name = osp.join(
                self.output_dir, basename + LabelFile.suffix
            )
        else:
            default_labelfile_name = osp.join(
                self.currentPath(), basename + LabelFile.suffix
            )
        filename = dlg.getSaveFileName(
            self.mainWnd, 'Choose File', default_labelfile_name,
            'Label files (*%s)' % LabelFile.suffix)
        filename, _ = filename
        filename = str(filename)
        return filename
   
 
    def changeOutputDirDialog(self, _value=False):
        default_output_dir = self.output_dir
        if default_output_dir is None and self.filename:
            default_output_dir = osp.dirname(self.filename)
        if default_output_dir is None:
            default_output_dir = self.currentPath()

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self.mainWnd, '%s - Save/Load Annotations in Directory' % __appname__,
            default_output_dir,
            QtWidgets.QFileDialog.ShowDirsOnly |
            QtWidgets.QFileDialog.DontResolveSymlinks,
        )
        output_dir = str(output_dir)

        if not output_dir:
            return

        self.output_dir = output_dir

        self.statusBar().showMessage(
            '%s . Annotations will be saved/loaded in %s' %
            ('Change Annotations Dir', self.output_dir))
        self.statusBar().show()

        current_filename = self.filename
        self.importDirImages(self.lastOpenDir, load=False)

        if current_filename in self.imageList:
            # retain currently selected file
            self.fileListWidget.setCurrentRow(
                self.imageList.index(current_filename))
            self.fileListWidget.repaint()
 
    def _saveFile(self, filename):
        if filename and self.saveLabels(filename):
            self.addRecentFile(filename)
            self.setClean()

    def closeFile(self, _value=False):
        if not self.mayContinue():
            return
        self.resetState()
        self.setClean()
        self.toggleActions(False)
        self.canvas.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

     
    def chooseColor1(self):
        color = self.colorDialog.getColor(
            self.lineColor, 'Choose line color', default=DEFAULT_LINE_COLOR)
        if color:
            self.lineColor = color
            # Change the color for all shape lines:
            #Shape.line_color = self.lineColor
            self.editor.setLineColor(self.lineColor)
            self.canvas.update()
            self.setDirty()

    def chooseColor2(self):
        color = self.colorDialog.getColor(
            self.fillColor, 'Choose fill color', default=DEFAULT_FILL_COLOR)
        if color:
            self.fillColor = color
            #Shape.fill_color = self.fillColor
            self.editor.setFillColor(self.fillColor)
            self.canvas.update()
            self.setDirty()
   

    def importLabelFile(self):
        formats = ['*.json']
        filters = "Label files (%s)" % ' '.join(formats)
        filename = QtWidgets.QFileDialog.getOpenFileName(
            self.mainWnd, '%s - import Label file' % __appname__,
            './', filters)
        filename, _ = filename
        filename = str(filename)
        if filename:
            with open(filename) as f:
                try:
                    data = json.load(f)
                    nodes = parseDict(data)
                    print('***weps------------------')
                    nodes.print()
                except Exception as e:
                    self.errorMessage('导入文件发生错误', '请检查json文件格式')
                    return
            shutil.copy(filename, './.label.json')
               

    def deleteSelectedShape(self):
        hasSelectedShape = self.editor.hasSelectedShape()
        if(not hasSelectedShape):
            self.errorMessage('没有选中的图形',
                                '请选择图形后再执行删除操作')
            return
        yes, no = QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No
        #msg = 'You are about to permanently delete this polygon, ' \
        #      'proceed anyway?'
        msg = '您正准备永久删除这个多边形, ' \
              '无论如何继续?'
        if yes == QtWidgets.QMessageBox.warning(self.mainWnd, '注意', msg,
                                                yes | no):
            self.remLabel(self.editor.deleteSelected())
            self.setDirty()
            if self.noShapes():
                for action in self.actions.onShapesPresent:
                    action.setEnabled(False)

    def chshapeLineColor(self):
        color = self.colorDialog.getColor(
            self.lineColor, 'Choose line color', default=DEFAULT_LINE_COLOR)
        if color:
            self.canvas.selectedShape.line_color = color
            self.canvas.update()
            self.setDirty()

    def chshapeFillColor(self):
        color = self.colorDialog.getColor(
            self.fillColor, 'Choose fill color', default=DEFAULT_FILL_COLOR)
        if color:
            self.canvas.selectedShape.fill_color = color
            self.canvas.update()
            self.setDirty()

    def copyShape(self):
        self.canvas.endMove(copy=True)
        self.addLabel(self.canvas.selectedShape)
        self.setDirty()

    def moveShape(self):
        self.canvas.endMove(copy=False)
        self.setDirty()    


    def copySelectedShape(self):
        print('*()copy selected shape')
        self.addLabel(self.editor.copySelectedShape())
        # fix copy and delete
        self.shapeSelectionChanged(True)

    def resetState(self):
        self.labelList.clear()
        self.filename = None
        self.imagePath = None
        self.imageData = None
        self.labelFile = None
        self.otherData = {} 
        # self.canvas.resetState() *

    @property
    def imageList(self):
        lst = []
        for i in range(self.fileListWidget.count()):
            item = self.fileListWidget.item(i)
            if(self.shortName):
                lst.append(self.short_long_name[item.text()])
            else:
                lst.append(item.text())
        return lst

    def isShortName(self, filename):
        return (filename.find('/')==-1) and (filename.find('\\')==-1)

    def loadFile(self, filename=None):
        """Load the specified file, or the last opened file if None."""
        print('* IS short name? ', self.shortName)
        if(self.isShortName(filename)):
            filename = self.short_long_name[filename]
        # changing fileListWidget loads file
        print('\n\n\n*-------------------------------------load a new file --------------------------------------------')
        if (filename in self.imageList and
                self.fileListWidget.currentRow() !=
                self.imageList.index(filename)):
            self.fileListWidget.setCurrentRow(self.imageList.index(filename))
            self.fileListWidget.repaint()
            return
        print('[python] resetState')
        self.resetState()
        if filename is None:
            filename = self.settings.value('filename', '')
        filename = str(filename)
        if not QtCore.QFile.exists(filename):
            self.errorMessage(
                'Error opening file', 'No such file: <b>%s</b>' % filename)
            print('*No such file')
            return False
        # assumes same name, but json extension
        self.status("Loading %s..." % osp.basename(str(filename)))
        label_file = osp.splitext(filename)[0] + '.json'
        if self.output_dir:
            label_file = osp.join(self.output_dir, label_file)
        #if find the label file for the image
        if QtCore.QFile.exists(label_file) and \
                LabelFile.isLabelFile(label_file):
            try:
                self.labelFile = LabelFile(label_file)
            except LabelFileError as e:
                self.errorMessage(
                    '打开文件时发生错误',
                    "<p><b>%s</b></p>"
                    "<p>确保 <i>%s</i> 是有效的标记文件"
                    % (e, label_file))
                self.status("读文件错误 %s" % label_file)
                return False
            self.imagePath = osp.join(
                osp.dirname(label_file),
                self.labelFile.imagePath,
            )
            self.lineColor = QtGui.QColor(*self.labelFile.lineColor)
            self.fillColor = QtGui.QColor(*self.labelFile.fillColor)
            self.otherData = self.labelFile.otherData
            self.geoTrans = self.otherData['geoTrans']
        
        # no matter there has a labelfile. we need to read file here.  some raster must 
        # get statistics
        print('*call gdal to read file')
        imageHandle = read(filename) #*
        if imageHandle is not None:
            # the filename is image not JSON
            self.imagePath = filename
            self.imageWidth = imageHandle.RasterXSize
            self.imageHeight = imageHandle.RasterYSize
            geoTrans = imageHandle.GetGeoTransform()
            if(math.isclose(geoTrans[0], 0)):
                self.geoTrans = [0,1,0, self.imageHeight, 0, -1]
            else:
                self.geoTrans = geoTrans
            self.otherData['geoTrans'] = self.geoTrans
            del imageHandle
        else:
            formats = ['*.{}'.format(fmt.data().decode())
                    for fmt in QtGui.QImageReader.supportedImageFormats()]
            self.errorMessage(
                'Error opening file',
                '<p>Make sure <i>{0}</i> is a valid image file.<br/>'
                'Supported image formats: {1}</p>'
                .format(filename, ','.join(formats)))
            self.status("Error reading %s" % filename)
            return False
            
        self.filename = filename
        if self._config['keep_prev']:
            prev_shapes = self.canvas.shapes
        
        # to display the image
        print('* clear shape')
        self.editor.clearShapes()
        self.iface.reset() #
        if self._config['flags']:
            self.loadFlags({k: False for k in self._config['flags']})
        if self._config['keep_prev']:
            self.loadShapes(prev_shapes)
            print('* load shapes prev ~!~')
        if self.labelFile:
            self.loadLabels(self.labelFile.shapes) #his shapes is not labelmeShape
            if self.labelFile.flags is not None:
                self.loadFlags(self.labelFile.flags)
        else:
            print('*the labelFile is None')

        self.setClean()
        self.paintCanvas()
        self.addRecentFile(self.filename)
        self.toggleActions(True)
        self.status("加载 %s" % osp.basename(str(filename)))
        return True 

    def setClean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.createMode.setEnabled(True)
        self.actions.createRectangleMode.setEnabled(True)
        self.actions.createCircleMode.setEnabled(True)
        self.actions.createLineMode.setEnabled(True)
        self.actions.createSlantRectMode.setEnabled(True)
        self.actions.createLineStripMode.setEnabled(True)
        title = __appname__
        if self.filename is not None:
            title = '{} - {}'.format(title, self.filename)
        self.mainWnd.setWindowTitle(title)

    def unload(self):
        """Function unloads the OSM Plugin.
        """
        self.dockWidget.close()

    def setEditMode(self):
        print('**set edit mode')
        self.toggleDrawMode(True)
 
    def showHideDockWidget(self):
        """Function shows/hides main dockable widget of the plugin ("OSM Feature" widget)
        """
        if self.dockWidget.isVisible():
            self.dockWidget.hide()
        else:
            self.dockWidget.show()

    # Callbacks
    def undoShapeEdit(self):
        '''
        self.editor.restoreShape()
        self.labelList.clear()
        self.loadShapes(self.editor.theShapes)
        self.actions.undo.setEnabled(self.editor.isShapeRestorable())
        '''

    def tutorial(self):
        url = 'https://github.com/enigma19971/RSLabel'  # NOQA
        webbrowser.open(url)

    def toggleAddPointEnabled(self, enabled):
        self.actions.addPoint.setEnabled(enabled)

    def toggleDrawingSensitive(self, drawing=True):
        """Toggle drawing sensitive.

        In the middle of drawing, toggling between modes should be disabled.
        """
        print('* toggleDrawingSensitive')
        self.actions.editMode.setEnabled(not drawing)
        self.actions.undoLastPoint.setEnabled(drawing)
        self.actions.undo.setEnabled(not drawing)
        self.actions.delete.setEnabled(not drawing)


    def toggleDrawMode(self, edit=True, createMode='polygon'):
        self.editor.setEditing(edit)
        self.editor.setCreateMode(createMode)   # set canvas 's creata mode.  *
        if edit:           
            self.actions.createMode.setEnabled(True)
            self.actions.createRectangleMode.setEnabled(True)
            self.actions.createCircleMode.setEnabled(True)
            self.actions.createLineMode.setEnabled(True)
            self.actions.createSlantRectMode.setEnabled(True)
            self.actions.createLineStripMode.setEnabled(True)
        else:
            if createMode == 'polygon':
                self.actions.createMode.setEnabled(False)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createSlantRectMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == 'rectangle':
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(False)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createSlantRectMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == 'line':
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(False)
                self.actions.createSlantRectMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == 'slantRectangle':
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createSlantRectMode.setEnabled(False)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "circle":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(False)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createSlantRectMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "linestrip":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createSlantRectMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(False)
            else:
                raise ValueError('Unsupported createMode: %s' % createMode)
        self.actions.editMode.setEnabled(not edit)


    def createDockWidgets(self):
        self.labelList = LabelQListWidget()
        self.lastOpenDir = None
        self.labelList.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.labelList.setParent(self.mainWnd)
        self.shape_dock = QtWidgets.QDockWidget('多边形标签', self.mainWnd)
        self.shape_dock.setObjectName('Labels')
        self.shape_dock.setWidget(self.labelList)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.shape_dock) #


        self.uniqLabelList = EscapableQListWidget()
        self.uniqLabelList.setToolTip(
            "Select label to start annotating for it. "
            "Press 'Esc' to deselect.")
        if self._config['labels']:
            self.uniqLabelList.addItems(self._config['labels'])
            self.uniqLabelList.sortItems()
        
        self.label_dock = QtWidgets.QDockWidget(u'标签列表', self.mainWnd)
        self.label_dock.setObjectName(u'Label List')
        self.label_dock.setWidget(self.uniqLabelList)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.label_dock) #

        self.fileSearch = QtWidgets.QLineEdit()
        self.fileSearch.setPlaceholderText('搜索文件')
        self.fileSearch.textChanged.connect(self.fileSearchChanged)
        self.showAllFiles = QtWidgets.QPushButton('显示所有')
        self.showAllFiles.setCheckable(True)
        self.showAllFiles.toggled.connect(self.onShowAllFiles)
        self.showAllFiles.setIcon(labelme.utils.newIcon('layers'))
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self.fileSearch)
        layout.addWidget(self.showAllFiles)
        self.fileListWidget = QtWidgets.QListWidget()
        self.fileListWidget.itemSelectionChanged.connect(
            self.fileSelectionChanged
        )

        fileListLayout = QtWidgets.QVBoxLayout()
        fileListLayout.setContentsMargins(0, 0, 0, 0)
        fileListLayout.setSpacing(0)
        #fileListLayout.addWidget(self.fileSearch)
        fileListLayout.addLayout(layout)
        fileListLayout.addWidget(self.fileListWidget)
        self.noPath = QtWidgets.QPushButton('隐藏路径')
        self.noPath.setCheckable(True)
        self.noPath.toggled.connect(self.onNoPath)
        self.openInExplorer = QtWidgets.QPushButton('打开文件夹')
        self.openInExplorer.clicked.connect(self.onOpenInExplorer)
        btlayout = QtWidgets.QHBoxLayout()
        btlayout.addWidget(self.noPath)
        btlayout.addWidget(self.openInExplorer)
        fileListLayout.addLayout(btlayout)
        self.file_dock = QtWidgets.QDockWidget(u'文件列表', self.mainWnd)
        self.file_dock.setObjectName(u'Files')
        fileListWidget = QtWidgets.QWidget()
        fileListWidget.setLayout(fileListLayout)
        self.file_dock.setWidget(fileListWidget)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.file_dock) #*

        self.flag_dock = self.flag_widget = None
        self.flag_dock = QtWidgets.QDockWidget('标记', self.mainWnd)
        self.flag_dock.setObjectName('Flags')
        self.flag_widget = QtWidgets.QListWidget()
        if self._config['flags']:
            self.loadFlags({k: False for k in config['flags']})
        self.flag_dock.setWidget(self.flag_widget)
        self.flag_widget.itemChanged.connect(self.setDirty)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.flag_dock)
        #signals and slots
        self.labelList.itemActivated.connect(self.labelSelectionChanged)
        self.labelList.itemSelectionChanged.connect(self.labelSelectionChanged)
        self.labelList.itemDoubleClicked.connect(self.editLabel)
        # Connect to itemChanged to detect checkbox changes.
        self.labelList.itemChanged.connect(self.labelItemChanged)
        self.labelList.setDragDropMode(
            QtWidgets.QAbstractItemView.InternalMove)

    def onNoPath(self,e):
        self.shortName =  e
        if(not self.shortName):
            for i in range(self.fileListWidget.count()):
                item = self.fileListWidget.item(i)
                item.setText(self.short_long_name[item.text()])
            self.noPath.setText('隐藏路径')
        else:
            for i in range(self.fileListWidget.count()):
                item = self.fileListWidget.item(i)
                item.setText(osp.basename(item.text()))
            self.noPath.setText('显示路径')
        print('* self.shortName', self.shortName)

    # Actions and menus
    def createActionsAndMenus(self):
        action = functools.partial(newAction, self.mainWnd) #*
        shortcuts = self._config['shortcuts']
        quit = action('&退出', self.mainWnd.close, shortcuts['quit'], 'quit',
                      'Quit application')
        open_ = action('&打开', self.openFile, shortcuts['open'], 'open',
                       'Open image or label file')
        #opendir = action('&Open Dir', self.openDirDialog,
        opendir = action('&打开文件夹', self.openDirDialog,
                         shortcuts['open_dir'], 'open', u'Open Dir')
        openNextImg = action(
            '&下一幅图像',
            self.openNextImg,
            shortcuts['open_next'],
            'next',
            u'Open next (hold Ctl+Shift to copy labels)',
            enabled=False,
        )
        openPrevImg = action(
            '&前一幅图像',
            self.openPrevImg,
            shortcuts['open_prev'],
            'prev',
            u'Open prev (hold Ctl+Shift to copy labels)',
            enabled=False,
        )
        save = action('&保存', self.saveFile, shortcuts['save'], 'save',
                      'Save labels to file', enabled=False)
        saveAs = action('&另存为', self.saveFileAs, shortcuts['save_as'],
                        'save-as', 'Save labels to a different file',
                        enabled=False)
        exportAs = action('&导出为', self.exportAs, shortcuts['export_as'],
                        'export', 'export labels to a coco/voc dataset format',
                        enabled=False)
        '''
        changeOutputDir = action(
            '&改变输出目录',
            slot=self.changeOutputDirDialog,
            shortcut=shortcuts['save_to'],
            icon='open',
            tip=u'Change where annotations are loaded/saved'
        )
        '''

        saveAuto = action(
            text='自动 &保存',
            slot=lambda x: self.actions.saveAuto.setChecked(x),
            icon='save',
            tip='自动保存',
            checkable=True,
            enabled=True,
        )
        saveAuto.setChecked(self._config['auto_save'])

        close = action('&关闭', self.closeFile, shortcuts['close'], 'close',
                       'Close current file')
        color1 = action('多边形 &线条颜色', self.chooseColor1,
                        shortcuts['edit_line_color'], 'color_line',
                        'Choose polygon line color')
        color2 = action('多边形 &填充颜色', self.chooseColor2,
                        shortcuts['edit_fill_color'], 'color',
                        'Choose polygon fill color')
        gridSzAndColor = action('网格 &尺寸颜色', self.setGridSizeAndColor,
                        shortcuts['grid_size_color'], 'grid',
                        'Choose grid color')

        import_label_file = action(
            '导入标签文件',
            self.importLabelFile,
            shortcuts['toggle_keep_prev_mode'], 'importLabel',
            'Toggle "keep pevious annotation" mode',
            checkable=False)

        createMode = action(
            '创建多边形',
            lambda: self.toggleDrawMode(False, createMode='polygon'),
            shortcuts['create_polygon'],
            'objects',
            'Start drawing polygons',
            enabled=False,
        )
        createRectangleMode = action(
            '创建矩形',
            lambda: self.toggleDrawMode(False, createMode='rectangle'),
            shortcuts['create_rectangle'],
            'sel_rect_plus',
            'Start drawing rectangles',
            enabled=False,
        )
        createCircleMode = action(
            '创建圆形 ',
            lambda: self.toggleDrawMode(False, createMode='circle'),
            shortcuts['create_circle'],
            'objects',
            'Start drawing circles',
            enabled=False,
        )
        createLineMode = action(
            '创建线段',
            lambda: self.toggleDrawMode(False, createMode='line'),
            shortcuts['create_line'],
            'objects',
            'Start drawing lines',
            enabled=False,
        )
        createSlantRectMode = action(
            '创建倾斜矩形',
            lambda: self.toggleDrawMode(False, createMode='slantRectangle'),
            shortcuts['create_point'],
            'objects',
            'Start drawing slant rectangle',
            enabled=False,
        )
        createLineStripMode = action(
            '创建线条',
            lambda: self.toggleDrawMode(False, createMode='linestrip'),
            shortcuts['create_linestrip'],
            'objects',
            'Start drawing linestrip. Ctrl+LeftClick ends creation.',
            enabled=False,
        )
        editMode = action('编辑多边形', self.setEditMode,
                          shortcuts['edit_polygon'], 'edit',
                          'Move and edit polygons', enabled=False)

        delete = action('删除多边形', self.deleteSelectedShape,
                        shortcuts['delete_polygon'], 'cancel',
                        'Delete', enabled=False)
        copy = action('复制多边形', self.copySelectedShape,
                      shortcuts['duplicate_polygon'], 'copy',
                      'Create a duplicate of the selected polygon',
                      enabled=False)
        undoLastPoint = action('撤销最后的点', self.editor.undoLastPoint,
                               shortcuts['undo_last_point'], 'undo',
                               'Undo last drawn point', enabled=False)
        addPoint = action('在边上添加点', self.editor.addPointToEdge,
                          None, 'edit', 'Add point to the nearest edge',
                          enabled=False)
        undo = action('撤销', self.undoShapeEdit, shortcuts['undo'], 'undo',
                      'Undo last add and edit of shape', enabled=False)

        hideAll = action('&隐藏\n多边形',
                         functools.partial(self.togglePolygons, False),
                         icon='eye', tip='Hide all polygons', enabled=False)
        showAll = action('&显示\n多边形',
                         functools.partial(self.togglePolygons, True),
                         icon='eye', tip='Show all polygons', enabled=False)

        help = action('&教程', self.tutorial, icon='help',
                      tip='Show tutorial page')

        edit = action('&编辑标记', self.editLabel, shortcuts['edit_label'],
                      'edit', 'Modify the label of the selected polygon',
                      enabled=False)

        shapeLineColor = action(
            '图形&线条颜色', self.chshapeLineColor, icon='color-line',
            tip='Change the line color for this specific shape', enabled=False)
        shapeFillColor = action(
            '图形&填充颜色', self.chshapeFillColor, icon='color',
            tip='Change the fill color for this specific shape', enabled=False)
        fill_drawing = action(
            '填充正在绘制的多边形',
            lambda x: self.canvas.setFillDrawing(x),
            None,
            'color',
            #'Fill polygon while drawing',
            '在绘制时填充多边形',
            checkable=True,
            enabled=True,
        )
        fill_drawing.setChecked(True)

        # Label list context menu.
        self.labelMenu = QtWidgets.QMenu()
        addActions(self.labelMenu, (edit, delete))
        self.labelList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.labelList.customContextMenuRequested.connect(
            self.popLabelListMenu)
        
        # Store actions for further handling.
        self.actions = struct(
            saveAuto=saveAuto,
            #changeOutputDir=changeOutputDir,
            save=save, saveAs=saveAs, open=open_, close=close,
            exportAs=exportAs,
            lineColor=color1, fillColor=color2,
            import_label_file=import_label_file,
            delete=delete, edit=edit, copy=copy,
            undoLastPoint=undoLastPoint, undo=undo, 
            addPoint=addPoint,
            createMode=createMode, editMode=editMode,
            createRectangleMode=createRectangleMode,
            createCircleMode=createCircleMode,
            createLineMode=createLineMode,
            createSlantRectMode=createSlantRectMode ,
            createLineStripMode=createLineStripMode,
            shapeLineColor=shapeLineColor, shapeFillColor=shapeFillColor,
            openNextImg=openNextImg, openPrevImg=openPrevImg,
            tool=(),
            editMenu=(edit, copy, delete, None, undo, #undoLastPoint,
                      None, color1, color2, gridSzAndColor, None, import_label_file),
            # menu shown at right click
            menu=(
                createMode,
                createRectangleMode,
                createCircleMode,
                createLineMode,
                createSlantRectMode,
                createLineStripMode,
                editMode,
                edit,
                copy,
                delete,
                shapeLineColor,
                shapeFillColor,
                undo,
                undoLastPoint,
                addPoint,
            ),
            onLoadActive=(
                close,
                createMode,
                createRectangleMode,
                createCircleMode,
                createLineMode,
                createSlantRectMode,
                createLineStripMode,
                editMode,
            ),
            onShapesPresent=(saveAs, hideAll, showAll),
        )
        # Menu buttons on Left
        self.actions.tool = (
            open_,
            opendir,
            openNextImg,
            openPrevImg,
            save,
            None,
            createMode,
            createRectangleMode,
            editMode,
            copy,
            delete,
            undo,
            None,
        )
        # Custom context menu for the canvas widget:
        addActions(self.canvasMenus[0], self.actions.menu)
        addActions(self.canvasMenus[1], (
            action('&拷贝到这里', self.copyShape),
            action('&移动到这里', self.moveShape)))

        self.menus = struct(
            file=self.menu('&文件'),
            edit=self.menu('&编辑'),
            view=self.menu('&视图'),
            help=self.menu('&帮助'),
            recentFiles=QtWidgets.QMenu('打开 &最近文件'),
            labelList=self.labelMenu,
        )
        addActions(self.menus.file, (open_, openNextImg, openPrevImg, opendir,
                                     self.menus.recentFiles,
                                     save, saveAs, saveAuto, #changeOutputDir,
                                     exportAs,
                                     close,
                                     None,
                                     quit))
        addActions(self.menus.help, (help,))
        addActions(self.menus.view, (
            self.flag_dock.toggleViewAction(),
            self.label_dock.toggleViewAction(),
            self.shape_dock.toggleViewAction(),
            self.file_dock.toggleViewAction(),
            self.fileInfo_dock.toggleViewAction(),
            None,
            fill_drawing,
            None,
            hideAll,
            showAll,
            None,
            #zoomIn,
            #zoomOut,
            #zoomOrg,
            None,
            #fitWindow,
            #fitWidth,
            None,
        ))
        self.menus.file.aboutToShow.connect(self.updateFileMenu)

    def setSignals(self):
        '''      
        #connect signal
        if self.output_file is not None and self._config['auto_save']:
            logger.warn(
                'If `auto_save` argument is True, `output_file` argument '
                'is ignored and output filename is automatically '
                'set as IMAGE_BASENAME.json.'
            )
        '''
        # this signal is export from riverMon
        self.editor.drawingPolygon.connect(self.toggleDrawingSensitive)
        self.editor.newShape.connect(self.newShape)
        self.editor.shapeMoved.connect(self.setDirty)
        self.editor.selectionChanged.connect(self.shapeSelectionChanged)
        self.editor.enabled.connect(self.editorEnabled)
        self.editor.edgeSelected.connect(self.actions.addPoint.setEnabled)
        self.editor.editorClose.connect(self.closeEvent)

    ########################################################################################################
    #                                         Utils
    ########################################################################################################
    def errorMessage(self, title, message):
        return QtWidgets.QMessageBox.critical(
            self.mainWnd, title, '<p><b>%s</b></p>%s' % (title, message))
    
    def statusBar(self):
        return self.mainWnd.statusBar()

    def status(self, message, delay=5000):
        self.mainWnd.statusBar().showMessage(message, delay)
    
    
    def popLabelListMenu(self, point):
        self.menus.labelList.exec_(self.labelList.mapToGlobal(point))

    def addRecentFile(self, filename):
        if filename in self.recentFiles:
            self.recentFiles.remove(filename)
        elif len(self.recentFiles) >= self.maxRecent:
            self.recentFiles.pop()
        self.recentFiles.insert(0, filename)

    def adjustScale(self, initial=False):
        '''
        value = self.scalers[self.FIT_WINDOW if initial else self.zoomMode]()
        self.zoomWidget.setValue(int(100 * value))
        '''
        pass 

    def paintCanvas(self):
        '''
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.scale = 0.01 * self.zoomWidget.value()
        self.canvas.adjustSize()
        self.canvas.update()  
        '''
        print('* call iface to openFile')
        self.iface.openFile(self.filename)
        pass

    def toggleActions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        '''
        for z in self.actions.zoomActions:
           z.setEnabled(value)
        '''
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def scanAllImages(self, folderPath):
        extensions = self.supportedFmts
        images = []        
        for root, dirs, files in os.walk(folderPath):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relativePath = osp.join(root, file)
                    images.append(relativePath)            
        images = set(images)
        images = list(images)
        images.sort(key=lambda x: x.lower())
        return images

    def scanTileImages(self, tiledImagefolder):
        '''
        scan the tiled image filder. return all tiled image in this folder.
        '''
        extensions = self.supportedFmts
        images = []
        for root, dirs, files in os.walk(tiledImagefolder):
            for dir in dirs:
                imgs = []
                for root_,  _, filess in os.walk(osp.join(root,dir)):
                    for file in filess:
                        if file.lower().endswith(tuple(extensions)):
                            relativePath = osp.join(root_, file)
                            imgs.append(relativePath)
                if(len(imgs) > 0):
                    imgs.sort(key=lambda x: x.lower())
                    images.append(imgs)
        return images

    def validateLabel(self, label):
        # no validation
        if self._config['validate_label'] is None:
            return True

        for i in range(self.uniqLabelList.count()):
            label_i = self.uniqLabelList.item(i).text()
            if self._config['validate_label'] in ['exact', 'instance']:
                if label_i == label:
                    return True
            if self._config['validate_label'] == 'instance':
                m = re.match(r'^{}-[0-9]*$'.format(label_i), label)
                if m:
                    return True
        return False

    def currentItem(self):
        items = self.labelList.selectedItems()
        if items:
            return items[0]
        return None

    def labelSelectionChanged(self):
        item = self.currentItem()
        if item and (self.editor.isEditing() or self.editor.canBreak()):
            self._noSelectionSlot = True
            shape = self.labelList.get_shape_from_item(item)
            self.editor.selectShape(shape)
            self.editor.moveToSelectedShape()

    def labelItemChanged(self, item):
        print('* labelItemChanged')
        shape = self.labelList.get_shape_from_item(item)
        print('* shape type is ', type(shape))
        label = str(item.text())
        if label != shape.getLabel():
            print('* shape label is not equal, shape.label={}'.format(shape.getLabel()))
            #shape.label = str(item.text())
            shape.setLabel(str(item.text()))
            self.setDirty()
        else:  # User probably changed item visibility
            print('*set visible') 
            self.editor.setShapeVisible(shape, item.checkState() == Qt.Checked)
    
    def loadRecent(self, filename):
        if self.mayContinue():
            self.loadFile(filename)

    def updateFileMenu(self):
        current = self.filename

        def exists(filename):
            return osp.exists(str(filename))

        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recentFiles if f != current and exists(f)]
        for i, f in enumerate(files):
            icon = newIcon('labels')
            action = QtWidgets.QAction(
                icon, '&%d %s' % (i + 1, QtCore.QFileInfo(f).fileName()), self.mainWnd)
            action.triggered.connect(functools.partial(self.loadRecent, f))
            menu.addAction(action)

    def mouseRelease(self,ev):
        if ev.button() == QtCore.Qt.RightButton:
            if self.editor.canBreak():
                menu = self.canvasMenus[0]
                menu.exec_(self.canvas.mapToGlobal(ev.pos()))           
        return True

    def editorEnabled(self, value):
        if(value):
            print('** editor is enabled from HOST')
        else:
            print('** editor is disabled from HOST')
        self.toggleActions(True)

    def chooseGridColor(self):
        color = self.colorDialog.getColor(
                        self.fillColor, 'Choose fill color', default=DEFAULT_FILL_COLOR)
        print('*',color)
        self.grid_dialog.btnColor.setStyleSheet('background-color: rgb({}, {}, {});'.format(color.red(),color.green(),color.blue()))
        self.grid_color = color

    def setGridSizeAndColor(self):
        self.grid_dialog = loadUi(here + '/GridSizeAndColorDialog.ui')
        self.grid_dialog.setWindowIcon(labelme.utils.newIcon('grid'))
        self.grid_dialog.btnColor.clicked.connect(self.chooseGridColor)
        #show grid size from settings
        self.grid_size = self.settings.value('grid_size')
        if(self.grid_size is None):
            self.grid_dialog.txtGridSize.setText('1024')
        else:
            self.grid_dialog.txtGridSize.setText('{}'.format(self.grid_size))
        
        ret = self.grid_dialog.exec()
        if(ret == 1): #accept
            self.grid_size = int(self.grid_dialog.txtGridSize.text())
            print('* Grid size', self.grid_size)
            if(self.grid_color is not None):
                self.iface.setGridColor(self.grid_color)
            self.iface.setGridSize(self.grid_size)
            self.settings.setValue('grid_size', self.grid_dialog.txtGridSize.text())
            self.settings.sync()

    

    def closeEvent(self):
        print('*^^^^^^^^^^^^^^^close')
        if not self.mayContinue():
            event.ignore()
        self.settings.setValue(
            'filename', self.filename if self.filename else '')
        self.settings.setValue('window/size', self.mainWnd.size())
        self.settings.setValue('window/position', self.mainWnd.pos())
        self.settings.setValue('window/state', self.mainWnd.saveState())
        self.settings.setValue('line/color', self.lineColor)
        self.settings.setValue('fill/color', self.fillColor)
        self.settings.setValue('recentFiles', self.recentFiles)
        self.settings.sync()
        # ask the use for where to save the labels
        # self.settings.setValue('window/geometry', self.saveGeometry())


    def onShowAllFiles(self, e):
        # to display the image
        if(len(self.imageList) <= 1):
            return
        mb = QtWidgets.QMessageBox
        msg = '<显示所有>功能，只针对已经配准好的图像集, 确定需要显示所有图层吗?'
        answer = mb.question(self.mainWnd,
                             '继续显示?',
                             msg,
                             mb.Yes | mb.Cancel,
                             mb.Cancel)
        if answer == mb.Cancel:
            return 
        if (e):
            self.editor.clearShapes()
            self.iface.reset() 
            self.iface.openFiles(self.imageList)
            self.actions.save.setEnabled(False)
            self.actions.createMode.setEnabled(False)
            self.actions.createRectangleMode.setEnabled(False)
            self.actions.createCircleMode.setEnabled(False)
            self.actions.createLineMode.setEnabled(False)
            self.actions.createSlantRectMode.setEnabled(False)
            self.actions.createLineStripMode.setEnabled(False)
            self.actions.editMode.setEnabled(False)
        else:
            self.editor.clearShapes()
            self.iface.reset() 
            self.iface.openFile(self.imageList[0])


########################################################################################################
#                                         EXPORT
########################################################################################################
    def exportAs(self):
            self.export_dialog = loadUi(here + '/ExportAsVocDialog.ui')
            self.export_dialog.setWindowIcon(labelme.utils.newIcon('export'))
            self.export_dialog.btnOutDir.clicked.connect(self.selectExportDir)
            export_dir = self.settings.value('export_dir')
            if(export_dir is not None):
                self.export_dialog.txtOutDir.setText(export_dir)
            else:
                ho = QDir.home().absolutePath()
                outdir = osp.join(ho,'rslabel')
                self.export_dialog.txtOutDir.setText(outdir.replace('/','\\'))
            tiled = self.settings.value('export_tiled')
            tileSize = self.settings.value('export_tile_size')
            if(tiled):
                self.export_dialog.chkTiled.setChecked(True)
                self.export_dialog.txtTileSize.setEnabled(True)
            if(tileSize):
                self.export_dialog.txtTileSize.setText(str(tileSize))
            else:
                self.export_dialog.txtTileSize.setText(str(1000))
            if not self.mayContinue():
                return
            if(self.export_dialog.exec() == 1):
                self.export()
            #save the settings
            self.settings.setValue('export_tile_size', self.export_dialog.txtTileSize.text())
            self.settings.setValue('export_tiled', self.export_dialog.chkTiled.isEnabled())
            self.settings.setValue('export_dir', self.export_dialog.txtOutDir.text())
            self.settings.sync()
            self.statusBar().showMessage('导出数据集成功')

    def selectOfflineLayerImportDir(self):
        targetDirPath = str(QtWidgets.QFileDialog.getExistingDirectory(
            self.mainWnd, '%s - Open Directory' % __appname__, '.',
            QtWidgets.QFileDialog.ShowDirsOnly |
            QtWidgets.QFileDialog.DontResolveSymlinks))
        self.offline_dialog.txtImportDir.setText(targetDirPath)
        self.offlineImportDir = targetDirPath

    def selectExportDir(self):
        targetDirPath = str(QtWidgets.QFileDialog.getExistingDirectory(
            self.mainWnd, '%s - Open Directory' % __appname__, '.',
            QtWidgets.QFileDialog.ShowDirsOnly |
            QtWidgets.QFileDialog.DontResolveSymlinks))
        self.export_dialog.txtOutDir.setText(targetDirPath)
        self.exportOutDir = targetDirPath

    def splitFile(self):
        '''
        split the files in the lastOpenDir, the raster file is split to sub blocks, and the 
        json file of labelme is plit too.
        return the output dir.
        '''
        print('\n\n\n*-------------------------------------SPLIT FILES--------------------------------------------')
        jsons = glob.glob(self.lastOpenDir + '/**/*.json', recursive=True)
        jsonNum = len(jsons)
        self.labels = set()
        exts = ['.tif','.env', '.pix', '.img', '.tiff', '.ecw', '.tga', '.jpg']
        extension = '.tif'
        for i, label_file in enumerate(jsons):
            #base = osp.splitext(osp.basename(label_file))[0]
            base = my_splitext(osp.basename(label_file))[0]
            filePathWithoutExt = my_splitext(label_file)[0]
            findImg = False
            for ext in exts:
                img_file = filePathWithoutExt + ext
                if(osp.exists(img_file)):
                    findImg = True
                    extension = ext
                    break
            if (findImg): #the json file has raster
                print('*',extension)
                tileSz = int(self.export_dialog.txtTileSize.text())      
                outDir = self.export_dialog.txtOutDir.text()
                outDir = osp.join(outDir , 'tiles', base)
                if(not osp.exists(outDir)):
                    os.makedirs(outDir)
                self.statusBar().showMessage('正在处理 %s' % img_file)
                validBlocks = []
                #load json
                print('* begin to load json file', label_file)
                with open(label_file) as f:
                    data = json.load(f)  #data is json file's content
                    imagePath = data['imagePath']
                    lineColor = data['lineColor']
                    fillColor = data['fillColor']
                    imageHeight = data['imageHeight']
                    imageWidth = data['imageWidth']
                    flags = data['flags']
                    otherData = {}
                    keys = [
                        'imageData',
                        'imagePath',
                        'lineColor',
                        'fillColor',
                        'shapes',  # polygonal annotations
                        'flags',   # image level flags
                        'imageHeight',
                        'imageWidth',]
                    for key, value in data.items():
                        if key not in keys:
                            otherData[key] = value
                    geoTrans = otherData['geoTrans']
                    mapfunc = functools.partial(img2map_p, geoTrans)
                    tile_x_count = math.ceil(imageWidth/tileSz)
                    tile_y_count = math.ceil(imageHeight/tileSz)
                    print('*',extension)
                    print('* @|@json load, image width is {}, image height is {}, tile_x_count is {}, tile_y_count is {}'.format(imageWidth, imageHeight, tile_x_count,tile_y_count))
                    for row in range(tile_y_count):
                        for col in range(tile_x_count):
                            if(col == (tile_x_count -1)):
                                iw = imageWidth - col * tileSz
                            else:
                                iw = tileSz
                            if(row == (tile_y_count -1)):
                                ih = imageHeight - row * tileSz
                            else:
                                ih = tileSz
                            #get the tiles rect (image coordination system)
                            tileRect = QtCore.QRectF(
                                col*tileSz,
                                row*tileSz,
                                iw, ih)
                            shapes = []
                            for s in data['shapes']:
                                self.labels.add(s['label'])
                                shape_type = s.get('shape_type', 'polygon')
                                points = s['points']
                                if(shape_type == 'rectangle'):
                                    rect = QtCore.QRectF(QPoint(*map2img(geoTrans,points[0][0],points[0][1])),
                                        QPoint(*map2img(geoTrans,points[1][0],points[1][1])))
                                    if(rect.intersects(tileRect)):
                                        print('* @|@ tile({},{}) get intersected rectangle, write to label ...'.format(row,col))
                                        intersected = tileRect.intersected(rect)
                                        if(math.isclose(geoTrans[0], 0)):
                                            UL = offset(tileSz, row, col, intersected.topLeft().x(), intersected.topLeft().y())
                                            LR = offset(tileSz, row, col, intersected.bottomRight().x(), intersected.bottomRight().y())
                                        else:
                                            UL = img2map(geoTrans,intersected.topLeft().x(), intersected.topLeft().y())
                                            LR = img2map(geoTrans,intersected.bottomRight().x(), intersected.bottomRight().y())
                                        copyS = copy.deepcopy(s)
                                        copyS['points'] = [UL,LR]
                                        shapes.append(copyS)                                        
                                elif(shape_type == 'polygon' or shape_type=='slantRectangle' ):
                                    tilePolygon = QtGui.QPolygonF(tileRect)
                                    ps = []
                                    for pnt in points:
                                        ps.append(QPointF(*map2img(geoTrans,pnt[0],pnt[1])))
                                    polygon = QtGui.QPolygonF(ps)
                                    polygon = polygon.intersected(tilePolygon)
                                    if(len(polygon) > 0):
                                        print('* @|@ tile({},{}) get intersected polygon, write to label ...'.format(row,col))
                                        copyS = copy.deepcopy(s)
                                        if(math.isclose(geoTrans[0], 0)):
                                            pts = [offset(tileSz, row, col, pnt.x(), pnt.y()) for pnt in polygon]
                                        else:
                                            pts = [(pnt.x(), pnt.y()) for pnt in polygon]
                                            pts = list(map(mapfunc, pts))
                                        copyS['points'] = pts 
                                        shapes.append(copyS) 
                            print('*',self.labels)
                            if(self.labels is None):
                                continue
                            label_file_t = osp.join(outDir, '{}_{}_{}.{}'.format(base, row, col, 'json'))
                            print('*',extension)
                            imagePath = '{}_{}_{}.{}'.format(base, row, col, extension[1:])
                            if (len(shapes) == 0):
                                continue
                            validBlocks.append(QtCore.QPoint(col, row))
                            #begin to create json file for the block file
                            if(math.isclose(geoTrans[0], 0)):
                                otherData['geoTrans'] = [0,1,0,ih,0,-1]
                            else:
                                otherData['geoTrans'] = [geoTrans[0]+geoTrans[1]*col*tileSz,
                                                            geoTrans[1],
                                                            geoTrans[2],
                                                            geoTrans[3] + geoTrans[5]*row*tileSz,
                                                            geoTrans[4],
                                                            geoTrans[5]]
                            print('* @|@ label_file_t', label_file_t)
                            lf = LabelFile()
                            try:
                                lf.save(
                                    filename=label_file_t,
                                    shapes=shapes,
                                    imagePath=imagePath,
                                    imageData=None,
                                    imageHeight=ih,
                                    imageWidth=iw,
                                    lineColor=lineColor,
                                    fillColor=fillColor,
                                    otherData=otherData,
                                    flags=flags,
                                )
                            except Exception as e:
                                self.errorMessage(
                                    '写标签文件失败',
                                    '关闭数据集文件夹后重试.')
                                return
                if(validBlocks):
                    self.iface.gdal2Tile(img_file,tileSz, outDir, validBlocks)
            labels_file = osp.join(here, 'labels.txt')
            with open(labels_file,'w') as f:
                f.write('__ignore__\n')
                f.write('_background_\n')
                for label in self.labels:
                    f.write(label+'\n')

            #write flags to labels.txt
        self.statusBar().showMessage('处理完毕')
        outDir = self.export_dialog.txtOutDir.text()
        outDir = osp.join(outDir , 'tiles')
        return outDir
      
   
    def export(self):
        self.exportOutDir = self.export_dialog.txtOutDir.text()
        if (not osp.exists(self.exportOutDir)):
            os.makedirs(self.exportOutDir)

        if os.listdir(self.exportOutDir):
            mb = QtWidgets.QMessageBox
            msg = '该目录非空,是否覆盖该文件夹中的内容 ?'
            answer = mb.question(self.mainWnd,
                                '该目录非空',
                                msg,
                                mb.Yes | mb.Cancel,
                                mb.Yes)
            if(answer == mb.Yes):
                try:
                    #shutil.rmtree(self.exportOutDir,ignore_errors=True)
                    outdir = self.exportOutDir.replace('/', '\\')
                    os.system('rd /s /q ' + outdir)
                except Exception as e:
                    print('*repr(e):\t', repr(e) )
                    print('* ^|^ remove file failed')
        if(self.export_dialog.radVOC.isChecked()):
            try:
                os.makedirs(osp.join(self.exportOutDir, 'JPEGImages'))
                os.makedirs(osp.join(self.exportOutDir, 'Annotations'))
                os.makedirs(osp.join(self.exportOutDir, 'AnnotationsVisualization'))
            except Exception:
                print('*Creating dataset failed:', self.exportOutDir)
        elif self.export_dialog.radCOCO.isChecked():
            os.makedirs(osp.join(self.exportOutDir, 'Annotations'))
        elif self.export_dialog.radYOLO.isChecked():
            try:
                os.makedirs(osp.join(self.exportOutDir, 'images'))
                os.makedirs(osp.join(self.exportOutDir, 'labels'))
                os.makedirs(osp.join(self.exportOutDir, 'AnnotationsVisualization'))
            except Exception:
                print('*Creating dataset failed:', self.exportOutDir)

        self.isTiled = False
        if(self.export_dialog.chkTiled.isChecked()):  #need to split to tiles
            out = self.splitFile()
            dir = out 
            self.isTiled = True
        else:
            jsons = glob.glob(self.lastOpenDir + '/**/*.json', recursive=True)
            jsonNum = len(jsons)
            self.labels = set()
            for label_file in jsons:
                with open(label_file) as f:
                    data = json.load(f)  #data is json file's content
                    for s in data['shapes']:
                        self.labels.add(s['label'])
            labels_file = osp.join(here, 'labels.txt')
            with open(labels_file,'w') as f:
                f.write('__ignore__\n')
                f.write('_background_\n')
                for label in self.labels:
                    f.write(label+'\n')
            dir = self.lastOpenDir

        if(self.export_dialog.radVOC.isChecked()):
            self.exportAsVOC(dir)
        elif self.export_dialog.radCOCO.isChecked():
            self.exportAsCOCO(dir)
        elif self.export_dialog.radYOLO.isChecked():
            self.exportAsYOLO(dir)
        mb = QtWidgets.QMessageBox
        msg =  '导出数据集成功,可查看数据集'
        answer = mb.information(self.mainWnd,
                            '导出数据完成',
                            msg)  
        os.startfile(self.export_dialog.txtOutDir.text())

    def exportAsCOCO(self, dir):
        if self.isTiled:
            self.exportTiledResultAsCOCO(dir)
        else:
            self.exportNoTiledResultAsCOCO(dir)

    def exportNoTiledResultAsCOCO(self, dir):
        jsons = glob.glob(dir + '/**/*.json', recursive=True)
        outdir = self.export_dialog.txtOutDir.text()
        for json in jsons:
            js = [json]
            output_json = osp.join(outdir, '{}.json'.format(my_basename(json)))
            labelme2coco(js, output_json)
            # move image files to Annotations folder
            # find the image file to be move
            exts = ['.tif','.env', '.pix', '.img', '.tiff', '.ecw', '.tga', '.jpg']
            e = '.tif'
            filePathWithoutExt = my_splitext(json)[0]
            findImg = False
            for ext in exts:
                img_file = filePathWithoutExt + ext
                if(osp.exists(img_file)):
                    findImg = True
                    e = ext
                    break 
            if findImg:
                subFolder = osp.join(outdir, 'Annotations')
                shutil.copy(img_file, subFolder)

    def exportTiledResultAsCOCO(self, dir):
        cds = childDir(dir)  #get next leve folder name. without path name
        for child in cds:
            jsons = glob.glob(osp.join(dir,child) + '/**/*.json', recursive=True)
            outdir = self.export_dialog.txtOutDir.text()
            output_json = osp.join(outdir, 'coco_{}.json'.format(child))
            labelme2coco(jsons, output_json)
            # move image files to Annotations folder
            for json in jsons:
                filePathWithoutExt = my_splitext(json)[0]
                #for every json file, we create a folder in Annotations
                subFolder = osp.join(outdir, 'Annotations', child)
                if(not osp.exists(subFolder)):
                    os.makedirs(subFolder)
                #find the image file to be move
                exts = ['.tif','.env', '.pix', '.img', '.tiff', '.ecw', '.tga', '.jpg']
                e = '.tif'
                findImg = False
                for ext in exts:
                    img_file = filePathWithoutExt + ext
                    if(osp.exists(img_file)):
                        findImg = True
                        e = ext
                        break 
                if findImg:
                    shutil.copy(img_file, subFolder)

    def onOpenInExplorer(self):
        if(self.lastOpenDir is not None):
            os.startfile(self.lastOpenDir)

    def exportAsVOC(self, dir):
        print('\n\n\n*-------------------------------------export as VOC--------------------------------------------')
        class_names = []
        class_name_to_id = {}
        labels_file = osp.join(here, 'labels.txt')
        print('*labels file:',labels_file)
        ##########     
        for i, line in enumerate(open(labels_file).readlines()):
            class_id = i - 1  # starts with -1
            class_name = line.strip()
            class_name_to_id[class_name] = class_id
            if class_id == -1:
                assert class_name == '__ignore__'
                continue
            elif class_id == 0:
                assert class_name == '_background_'
            class_names.append(class_name)
        class_names = tuple(class_names)
        print('*class_names:', class_names)
        out_class_names_file = osp.join(self.exportOutDir, 'class_names.txt')
        with open(out_class_names_file, 'w') as f:
            f.writelines('\n'.join(class_names))
        print('*Saved class_names:', out_class_names_file)
        #########
        jsons = glob.glob(dir + '/**/*.json', recursive=True)
        print('*export dir: {}'.format(dir))
        jsonNum = len(jsons)
        for i, label_file in enumerate(jsons):
            with open(label_file) as f:
                data = json.load(f)  #data is json file's content
                #get geo trans parameters from json file
                otherData = {}
                keys = [
                    'imageData',
                    'imagePath',
                    'lineColor',
                    'fillColor',
                    'shapes',  # polygonal annotations
                    'flags',   # image level flags
                    'imageHeight',
                    'imageWidth',]
                for key, value in data.items():
                    if key not in keys:
                        otherData[key] = value
                geoTrans = otherData['geoTrans']
            #make dirs for voc
            base = osp.splitext(osp.basename(label_file))[0]
            out_img_file = osp.join(
                self.exportOutDir, 'JPEGImages', data['imagePath'])
            out_xml_file = osp.join(
                self.exportOutDir, 'Annotations', base + '.xml')
            out_viz_file = osp.join(
                self.exportOutDir, 'AnnotationsVisualization', base + '.tif')
            # get the image file to copy to ...
            img_file = osp.join(osp.dirname(label_file), data['imagePath'])
            print('*export',img_file)
            print('*to', out_img_file)
            shape = gdalCopy(img_file, out_img_file)
            self.statusBar().showMessage('正在拷贝文件{}'.format(img_file))
            maker = lxml.builder.ElementMaker()
            xml = maker.annotation(
                maker.folder('JPEGImages'),
                maker.filename(data['imagePath']),
                maker.path(out_img_file),
                maker.source(maker.database('Unknown')),    # e.g., The VOC2007 Database
                maker.size(
                    maker.height(str(shape[0])),
                    maker.width(str(shape[1])),
                    maker.depth(str(shape[2])),
                ),
                maker.segmented('0'),
            )
            print('*VOC image, size: width {}, height {}, raster {}'.format(shape[0],shape[1],shape[2]))
            bboxes = []
            labels = []
            colors = [] 
            unkown_class_type = False 
            for shape in data['shapes']:
                if shape['shape_type'] != 'rectangle' \
                    and shape['shape_type'] != 'polygon' \
                    and shape['shape_type'] != 'slantRectangle':
                    print('*Skipping shape: label={label}, shape_type={shape_type}'
                        .format(**shape))
                    continue
                class_name = shape['label']
                print('*class_name', class_name)
                try:
                    class_id = class_names.index(class_name)
                except Exception as e:
                    unkown_class_type = True
                    break
                if(shape['shape_type'] == 'rectangle'):
                    (xmin_, ymin_), (xmax_, ymax_) = shape['points']
                elif(shape['shape_type'] == 'polygon'):
                    (xmin_, ymin_), (xmax_, ymax_) = boundingBox(shape['points'])
                elif(shape['shape_type'] == 'slantRectangle'):
                    (xmin_, ymin_), (xmax_, ymax_) = boundingBox(shape['points'])

                #convert to image coordination here
                xmin = (xmin_ - geoTrans[0]) / geoTrans[1]
                ymin = (geoTrans[3] - ymin_) / -geoTrans[5]
                xmax = (xmax_ - geoTrans[0]) / geoTrans[1]
                ymax = (geoTrans[3] - ymax_) / -geoTrans[5]
                if xmax < xmin:
                    xmax, xmin = xmin, xmax
                if ymax < ymin:
                    ymax, ymin = ymin, ymax

                bboxes.append(QRect(QPoint(xmin,ymin),QPoint(xmax,ymax))) 
                labels.append(class_id)
                xml.append(
                    maker.object(
                        maker.name(shape['label']),
                        maker.pose('Unspecified'),
                        maker.truncated('0'),
                        maker.difficult('0'),
                        maker.probability(str(shape['probability'])),
                        maker.bndbox(
                            maker.xmin(str(int(xmin))),
                            maker.ymin(str(int(ymin))),
                            maker.xmax(str(int(xmax))),
                            maker.ymax(str(int(ymax))),
                        ),
                    )
                )
            if (unkown_class_type):
                break  #next json file
            captions = [class_names[l] for l in labels]
            colormap = labelme.utils.label_colormap(255)
            for label in labels:
                color = (colormap[label]*255).astype(np.uint8)
                colors.append(QColor(*color))
            print('*captions {},  labels {},  colors {}'.format(captions, labels, colors))
           
            if(captions and self.isTiled):
                self.statusBar().showMessage('正在给文件{}画实例'.format(img_file))
                (pathName,extension) = os.path.splitext(img_file)
                omd = pathName + '.omd'
                if(not osp.exists(omd)):
                    img = read(img_file)
                    del img
                self.iface.draw_instances(img_file, out_viz_file, bboxes, colors, captions)  

            if(not self.isTiled):
                readme = osp.join(
                    self.exportOutDir, 'AnnotationsVisualization', 'readme.txt')
                with open(readme,'w') as f:
                    f.write('未分块的输入文件不支持draw instance操作')
            #write xml
            with open(out_xml_file, 'wb') as f:
                f.write(lxml.etree.tostring(xml, encoding='utf-8' ,pretty_print=True))
            self.iface.setProgress((int)((i+1)*100.0/jsonNum))
            i = i + 1

    def exportAsYOLO(self, dir):
        print('\n\n\n*-------------------------------------export as YOLO--------------------------------------------')
        class_names = []
        class_name_to_id = {}
        labels_file = osp.join(here, 'labels.txt')
        print('*labels file:',labels_file)
        ##########     
        for i, line in enumerate(open(labels_file).readlines()):
            class_id = i - 1  # starts with -1
            class_name = line.strip()
            class_name_to_id[class_name] = class_id
            if class_id == -1:
                assert class_name == '__ignore__'
                continue
            elif class_id == 0:
                assert class_name == '_background_'
            class_names.append(class_name)
        class_names = tuple(class_names)
        print('*class_names:', class_names)
        out_class_names_file = osp.join(self.exportOutDir, 'class_names.txt')
        with open(out_class_names_file, 'w') as f:
            f.writelines('\n'.join(class_names))
        print('*Saved class_names:', out_class_names_file)
        #########
        jsons = glob.glob(dir + '/**/*.json', recursive=True)
        print('*export dir: {}'.format(dir))
        jsonNum = len(jsons)
        for i, label_file in enumerate(jsons):
            with open(label_file) as f:
                data = json.load(f)  #data is json file's content
                #get geo trans parameters from json file
                otherData = {}
                keys = [
                    'imageData',
                    'imagePath',
                    'lineColor',
                    'fillColor',
                    'shapes',  # polygonal annotations
                    'flags',   # image level flags
                    'imageHeight',
                    'imageWidth',]
                for key, value in data.items():
                    if key not in keys:
                        otherData[key] = value
                geoTrans = otherData['geoTrans']
            #make dirs for yolo
            base = osp.splitext(osp.basename(label_file))[0]
            out_img_file = osp.join(
                self.exportOutDir, 'images', data['imagePath'])
            out_txt_file = osp.join(
                self.exportOutDir, 'labels', base + '.txt')
            out_viz_file = osp.join(
                self.exportOutDir, 'AnnotationsVisualization', base + '.tif')
            # get the image file to copy to ...
            img_file = osp.join(osp.dirname(label_file), data['imagePath'])
            print('*export',img_file)
            print('*to', out_img_file)
            shape = gdalCopy(img_file, out_img_file)
            self.statusBar().showMessage('正在拷贝文件{}'.format(img_file))
            height, width = shape[:2]
            yololines = []
            print('*VOC image, size: width {}, height {}, raster {}'.format(shape[0],shape[1],shape[2]))
            bboxes = []
            labels = []
            colors = [] 
            unkown_class_type = False 
            for shape in data['shapes']:
                if shape['shape_type'] != 'rectangle' \
                    and shape['shape_type'] != 'polygon' \
                    and shape['shape_type'] != 'slantRectangle':
                    print('*Skipping shape: label={label}, shape_type={shape_type}'
                        .format(**shape))
                    continue
                class_name = shape['label']
                print('*class_name', class_name)
                try:
                    class_id = class_names.index(class_name)
                except Exception as e:
                    unkown_class_type = True
                    break
                if(shape['shape_type'] == 'rectangle'):
                    (xmin_, ymin_), (xmax_, ymax_) = shape['points']
                elif(shape['shape_type'] == 'polygon'):
                    (xmin_, ymin_), (xmax_, ymax_) = boundingBox(shape['points'])
                elif(shape['shape_type'] == 'slantRectangle'):
                    (xmin_, ymin_), (xmax_, ymax_) = boundingBox(shape['points'])

                #convert to image coordination here
                xmin = (xmin_ - geoTrans[0]) / geoTrans[1]
                ymin = (geoTrans[3] - ymin_) / -geoTrans[5]
                xmax = (xmax_ - geoTrans[0]) / geoTrans[1]
                ymax = (geoTrans[3] - ymax_) / -geoTrans[5]
                if xmax < xmin:
                    xmax, xmin = xmin, xmax
                if ymax < ymin:
                    ymax, ymin = ymin, ymax

                bboxes.append(QRect(QPoint(xmin,ymin),QPoint(xmax,ymax))) 
                labels.append(class_id)
                xc = (xmax + xmin) / 2 / width
                yc = (ymax + ymin) / 2 / height
                w = (xmax - xmin) / width
                h = (ymax - ymin) / height
                yololines.append(' '.join(map(str, (class_id, xc, yc, w, h))))
            if (unkown_class_type):
                break  #next json file
            captions = [class_names[l] for l in labels]
            colormap = labelme.utils.label_colormap(255)
            for label in labels:
                color = (colormap[label]*255).astype(np.uint8)
                colors.append(QColor(*color))
            print('*captions {},  labels {},  colors {}'.format(captions, labels, colors))
           
            if(captions and self.isTiled):
                self.statusBar().showMessage('正在给文件{}画实例'.format(img_file))
                (pathName,extension) = os.path.splitext(img_file)
                omd = pathName + '.omd'
                if(not osp.exists(omd)):
                    img = read(img_file)
                    del img
                self.iface.draw_instances(img_file, out_viz_file, bboxes, colors, captions)  

            if(not self.isTiled):
                readme = osp.join(
                    self.exportOutDir, 'AnnotationsVisualization', 'readme.txt')
                with open(readme,'w') as f:
                    f.write('未分块的输入文件不支持draw instance操作')
            #write txt
            with open(out_txt_file, 'w') as f:
                f.write('\n'.join(yololines))
            self.iface.setProgress((int)((i+1)*100.0/jsonNum))
            i = i + 1

    def map2img(self, x, y):
        u = (x - self.geoTrans[0]) / self.geoTrans[1]
        v = (self.geoTrans[3] - y) / -self.geoTrans[5]
        return u, v
    
    def img2map(self, x, y):
        u = self.geoTrans[0] + self.geoTrans[1]*x
        v = self.geoTrans[3] + self.geoTrans[5]*y
        return u ,v 

    def img2map_p(self, p):
        u = self.geoTrans[0] + self.geoTrans[1]*p[0]
        v = self.geoTrans[3] + self.geoTrans[5]*p[1]
        return u ,v 

    def loadJson(self, json_file):
        filename = json_file
        self.status("Loading %s..." % osp.basename(str(filename)))
        label_file = osp.splitext(filename)[0] + '_label.json'
        #if find the label file for the image
        if QtCore.QFile.exists(label_file) and \
                LabelFile.isLabelFile(label_file):
            try:
                self.labelFile = LabelFile(label_file)
            except LabelFileError as e:
                self.errorMessage(
                    '打开文件时发生错误',
                    "<p><b>%s</b></p>"
                    "<p>确保 <i>%s</i> 是有效的标记文件"
                    % (e, label_file))
                self.status("读文件错误 %s" % label_file)
                return False
            self.imagePath = osp.join(
                osp.dirname(label_file),
                self.labelFile.imagePath,
            )
            self.lineColor = QtGui.QColor(*self.labelFile.lineColor)
            self.fillColor = QtGui.QColor(*self.labelFile.fillColor)
            self.otherData = self.labelFile.otherData
            self.geoTrans = self.otherData['geoTrans']
        
        # no matter there has a labelfile. we need to read file here.  some raster must 
        # get statistics
        #parse the json file
        try:
            with open(json_file, 'r') as fp:
                data = json.load(fp)  #
                self.imagePath = json_file 
                self.imageWidth = data['width']
                self.imageHeight = data['height']
                hasGeo = data['hasGeo']
                if(hasGeo):
                    self.geoTrans = data['geoTrans']
                else:
                    self.geoTrans = [0,1,0, self.imageHeight, 0, -1]
                self.otherData['geoTrans'] = self.geoTrans
        except :
            formats = ['*.{}'.format(fmt.data().decode())
                    for fmt in QtGui.QImageReader.supportedImageFormats()]
            self.errorMessage(
                'Error opening file',
                '<p>Make sure <i>{0}</i> is a valid image file.<br/>'
                'Supported image formats: {1}</p>'
                .format(filename, ','.join(formats)))
            self.status("Error reading %s" % filename)
            return False
            
        self.filename = filename
        if self._config['keep_prev']:
            prev_shapes = self.canvas.shapes
        
        # to display the image
        print('[python] clear shape')
        self.editor.clearShapes()
        self.iface.reset() #
        if self._config['flags']:
            self.loadFlags({k: False for k in self._config['flags']})
        if self._config['keep_prev']:
            self.loadShapes(prev_shapes)
            print('[python] load shapes prev ~!~')
        if self.labelFile:
            self.loadLabels(self.labelFile.shapes) #his shapes is not labelmeShape
            if self.labelFile.flags is not None:
                self.loadFlags(self.labelFile.flags)
        else:
            print('[python] the labelFile is None')

        self.setClean()
        print('* call iface to openFile')
        self.iface.openFile(self.filename)
        self.addRecentFile(self.filename)
        self.toggleActions(True)
        self.status("加载 %s" % osp.basename(str(filename)))
        return True 
########################################################################################################
#                                          GDAL                                        
########################################################################################################
import numpy as np
def read(filename):
    img = None
    try:
        img = gdal.Open(filename)
        if(img is None):
            return None

        datatype = img.GetRasterBand(1).DataType
        print('* @|@ read file, datatype$$$$$$$$$$$$$$$$$$$$$$$$$$$$$', datatype) 
        '''
        desc = img.GetDescription()
        metadata = img.GetMetadata() #
        print('*Raster description: {desc}'.format(desc=desc))
        print('*Raster metadata:')
        print(metadata) # {'AREA_OR_POINT': 'Area'}
        print('\n')
        '''
        if (datatype != 1):
            bandNum = img.RasterCount
            (filepath,tempfilename) = os.path.split(filename)
            (shotname,extension) = os.path.splitext(tempfilename)
            omd = filepath + '/' + shotname + '.omd'
            print('*the omd file is', omd)
            if not osp.exists(omd):
                omdf = open(omd, 'w')
                omdf.write('number_bands:  {}\n\n'.format(bandNum))
                for bandIdx in np.arange(1, bandNum+1):
                    band = img.GetRasterBand(int(bandIdx))
                    stats = band.GetStatistics(0,1) #if no statistic , it will compute
                    omdf.write('band{}.min_value:  {}\n'.format(bandIdx, stats[0]))
                    omdf.write('band{}.max_value:  {}\n'.format(bandIdx, stats[1]))
                    print('*', stats)
    except Exception:
        print('*gdal read {}, failed'.format(filename))
        exstr = traceback.format_exc()
        print (exstr)
    return img
        
def gdalCopy(src_filename, dst_filename):
    src_ds = gdal.Open( src_filename )
    #Open output format driver, see gdal_translate --formats for list
    #format = "GTiff"
    #driver = gdal.GetDriverByName( format )
    #Output to new format
    #dst_ds = driver.CreateCopy( dst_filename, src_ds, 0 )
    #Properly close the datasets to flush to disk
    #dst_ds = None
    w, h, d = src_ds.RasterXSize, src_ds.RasterYSize, src_ds.RasterCount
    src_ds = None
    shutil.copy(src_filename, dst_filename)
    return w,h,d

########################################################################################################
#                                          Utils                                        
########################################################################################################

def my_basename(pathname):
    """splitext for paths with directories that may contain dots."""
    pathname = pathname.replace('\\', '/')
    x = pathname.split('/')
    path = x[-1]
    ret, _ = my_splitext(path)
    return ret


def my_splitext(pathname):
    """splitext for paths with directories that may contain dots."""
    x = pathname.split(os.extsep)
    path = x[0]
    for ext in x[1:-1]:
        path = path + '.' + ext
    return path, x[-1]

def boundingBox(points):
    min_x, min_y = np.min(points, 0)[0], np.min(points, 0)[1]
    max_x, max_y = np.max(points, 0)[0], np.max(points, 0)[1]
    return (min_x, min_y), (max_x, max_y)

def childDir(dir):
    dirs = []
    files = os.listdir(dir)
    for f in files:
        fullPathName = osp.join(dir,f)
        if osp.isdir(fullPathName):
            dirs.append(f)
    return dirs

class JsonNode(object):
    def __init__(self, name = None):
        if name is not None:
            self.name = name
        else:
            self.name = None
        self.children = []
        self.parent = None

    def setParent(self, p):
        self.parent = p
    
    def getParent(self):
        p = self.parent
        while p.name is None:
            p = p.parent
        return p

    def setName(self, name):
        self.name = name

    def addChild(self, c):
        self.children.append(c)
    
    def print(self, level = 0):
        if(self.name is not None):
            print('-'*level + self.name)
        else:
            print('-'*level + 'No Name')
        for c in self.children:
            c.print(level+1)

    def leafs(self):
        ''' get all leaf node'''
        ls = []
        for c in self.children:
            if (not c.children):
                ls.append(c.name)
            else:
                u = c.leafs()
                for x in u:
                    ls.append(x)
        return ls




def parseDict(data, root = None):
    root = JsonNode()
    for key, value in data.items():
        print('*key= ', key)
        print('*value= ', value)
        node = JsonNode(key)
        value_is_list = isinstance(value, list)
        value_is_dict = isinstance(value, dict)
        value_is_str  = isinstance(value, str)
        if(value_is_str):
            child = JsonNode(name = value)
            child.setParent(node)
        elif value_is_dict:
            child = parseDict(value)
            child.setParent(node)
            node.addChild(child)
        elif value_is_list:
            parseList(value,node)
        root.addChild(node)
    return root 