# -*- coding: utf-8 -*-
"""
QGIS utilities module

"""

from PyQt5.QtCore import QCoreApplication, QLocale
# from qgis.core import QGis
import sys
import os
import traceback
import glob
import os.path
import re


print("[here is]:", __file__, sys._getframe().f_lineno)
#######################
# ERROR HANDLING


def showException(type, value, tb, msg):
    lst = traceback.format_exception(type, value, tb)
    if msg == None:
        msg = QCoreApplication.translate(
            'Python', 'An error has occured while executing Python code:')
    txt = ' {}'.format(msg)
    for s in lst:
        txt += s
    print(txt)


def qgis_excepthook(type, value, tb):
    showException(type, value, tb, None)


def installErrorHook():
    sys.excepthook = qgis_excepthook


def uninstallErrorHook():
    sys.excepthook = sys.__excepthook__


# install error hook() on module load
installErrorHook()

# initialize 'iface' object
iface = None


def initInterface(pointer):
    print("[here is]:", __file__, sys._getframe().f_lineno)
    try:
        from sip import wrapinstance
        from rslabel.gui import QgisInterface
        global iface
        print('[rslabel.utils]:begin to wrap instance...')
        iface = wrapinstance(pointer, QgisInterface)
        print('[rslabel.utils]:wrap instance end')
    except:
        print('[rslabel.utils]: can not initialize interface')
        traceback.print_exc()


#######################
# PLUGINS

# list of plugin paths. it gets filled in by the QGIS python library
plugin_paths = ['plugins', 'python/plugins']

# dictionary of plugins
plugins = {}

# list of active (started) plugins
active_plugins = []

# list of plugins in plugin directory and home plugin directory
available_plugins = []


def findPlugins(path):
    plugins = []
    for plugin in glob.glob(path + "/*"):
        if os.path.isdir(plugin) and os.path.exists(os.path.join(plugin, '__init__.py')):
            plugins.append(os.path.basename(plugin))
    return plugins


def updateAvailablePlugins():
    print("[here is]:", __file__, sys._getframe().f_lineno)
    """ go thrgouh the plugin_paths list and find out what plugins are available """
    # merge the lists
    plugins = []
    print("[here is]:", __file__, sys._getframe().f_lineno)
    for pluginpath in plugin_paths:
        for p in findPlugins(pluginpath):
            if p not in plugins:
                plugins.append(p)

    global available_plugins
    available_plugins = plugins
    print("[here is]:", __file__, sys._getframe().f_lineno)


def pluginMetadata(packageName, fct):
    """ fetch metadata from a plugin """
    try:
        package = sys.modules[packageName]
        return getattr(package, fct)()
    except Exception as e:
        print('*get Plugin Meta data error', e)
        return "__error__"


""" load plugin's package """


def loadPlugin(packageName):
    try:
        __import__(packageName)
        print('*load plugin ', packageName)
        return True
    except:
        print('*load plugin {} failed'.format(packageName))
        exstr = traceback.format_exc()
        print(exstr)
        pass  # continue...

    # snake in the grass, we know it's there
    sys.path_importer_cache.clear()

    # retry
    try:
        __import__(packageName)
        return True
    except:
        msgTemplate = QCoreApplication.translate(
            "Python", "Couldn't load plugin '%1' from ['%2']")
        msg = msgTemplate.arg(packageName).arg("', '".join(sys.path))
        showException(sys.exc_type, sys.exc_value, sys.exc_traceback, msg)
        return False

def openFile(filename):
    #这个函数是在c++里面调用的   2021.1.23
    plugins['labelme'].loadRemoteFile(filename)

def startPlugin(packageName):
    """ initialize the plugin """
    global plugins, active_plugins, iface
    print('*start the plugin {}'.format(packageName))
    if packageName in active_plugins:
        print('*the plugin {} is active , return'.format(packageName))
        return False

    package = sys.modules[packageName]
    errMsg = "Python", "Couldn't load plugin "

    # create an instance of the plugin
    try:
        plugins[packageName] = package.classFactory(iface)
        print('*load the plugin {}, successfully'.format(packageName))
        print('*here')
    except Exception as e:
        print('*load the plugin {}, failed'.format(packageName))
        exstr = traceback.format_exc()
        print(exstr)
        _unloadPluginModules(packageName)
        msg = ("Python", "%1 due an error when calling its classFactory() method")
        showException(sys.exc_type, sys.exc_value, sys.exc_traceback, msg)
        return False

    # initGui
    try:
        plugins[packageName].initGui()
    except Exception as e:
        print('*load the plugin {}, init Gui, failed'.format(packageName))
        exstr = traceback.format_exc()
        print(exstr)
        del plugins[packageName]
        _unloadPluginModules(packageName)
        msg = QCoreApplication.translate(
            "Python", "%1 due an error when calling its initGui() method").arg(errMsg)
        showException(sys.exc_type, sys.exc_value, sys.exc_traceback, msg)
        return False

    # add to active plugins
    active_plugins.append(packageName)
    print('*load the plugin {} successfully  :-)'.format(packageName))

    return True


def canUninstallPlugin(packageName):
    """ confirm that the plugin can be uninstalled """
    global plugins, active_plugins

    if not plugins.has_key(packageName):
        return False
    if packageName not in active_plugins:
        return False

    try:
        metadata = plugins[packageName]
        if "canBeUninstalled" not in dir(metadata):
            return True
        return bool(metadata.canBeUninstalled())
    except:
        msg = "Error calling "+packageName+".canBeUninstalled"
        showException(sys.exc_type, sys.exc_value, sys.exc_traceback, msg)
        return True


def unloadPlugin(packageName):
    """ unload and delete plugin! """
    global plugins, active_plugins

    if not plugins.has_key(packageName):
        return False
    if packageName not in active_plugins:
        return False

    try:
        plugins[packageName].unload()
        del plugins[packageName]
        active_plugins.remove(packageName)
        _unloadPluginModules(packageName)
        return True
    except Exception as e:
        msg = QCoreApplication.translate(
            "Python", "Error while unloading plugin %1").arg(packageName)
        showException(sys.exc_type, sys.exc_value, sys.exc_traceback, msg)
        return False


def _unloadPluginModules(packageName):
    """ unload plugin package with all its modules (files) """
    global _plugin_modules
    mods = _plugin_modules[packageName]

    for mod in mods:
        # if it looks like a Qt resource file, try to do a cleanup
        # otherwise we might experience a segfault next time the plugin is loaded
        # because Qt will try to access invalid plugin resource data
        try:
            if hasattr(sys.modules[mod], 'qCleanupResources'):
                sys.modules[mod].qCleanupResources()
        except:
            pass
        # try to remove the module from python
        try:
            del sys.modules[mod]
        except:
            pass
    # remove the plugin entry
    del _plugin_modules[packageName]


def isPluginLoaded(packageName):
    print("*find out whether plugin {} is active (i.e. has been started)".format(packageName))
    global plugins, active_plugins
    if (packageName not in plugins):
        return False
    ret = (packageName in active_plugins)
    return ret


def reloadPlugin(packageName):
    """ unload and start again a plugin """
    global active_plugins
    if packageName not in active_plugins:
        return  # it's not active

    unloadPlugin(packageName)
    loadPlugin(packageName)
    startPlugin(packageName)


def showPluginHelp(packageName=None, filename="index", section=""):
    """ show a help in the user's html browser. The help file should be named index-ll_CC.html or index-ll.html"""
    try:
        source = ""
        if packageName is None:
            import inspect
            source = inspect.currentframe().f_back.f_code.co_filename
        else:
            source = sys.modules[packageName].__file__
    except:
        return
    path = os.path.dirname(source)
    locale = str(QLocale().name())
    helpfile = os.path.join(path, filename+"-"+locale+".html")
    if not os.path.exists(helpfile):
        helpfile = os.path.join(
            path, filename+"-"+locale.split("_")[0]+".html")
    if not os.path.exists(helpfile):
        helpfile = os.path.join(path, filename+"-en.html")
    if not os.path.exists(helpfile):
        helpfile = os.path.join(path, filename+"-en_US.html")
    if not os.path.exists(helpfile):
        helpfile = os.path.join(path, filename+".html")
    if os.path.exists(helpfile):
        url = "file://"+helpfile
        if section != "":
            url = url + "#" + section
        iface.openURL(url, False)


def pluginDirectory(packageName):
    """ return directory where the plugin resides. Plugin must be loaded already """
    return os.path.dirname(sys.modules[packageName].__file__)


#######################
# IMPORT wrapper
_uses_builtins = True
try:
    import builtins
    _builtin_import = builtins.__import__
except AttributeError:
    _uses_builtins = False
    import __builtin__
    _builtin_import = __builtin__.__import__

_plugin_modules = {}


def _import(name, globals={}, locals={}, fromlist=[], level=None):
    """
    Wrapper around builtin import that keeps track of loaded plugin modules and blocks
    certain unsafe imports
    """
    if level is None:
        level = 0

    if 'PyQt4' in name:
        msg = 'PyQt4 classes cannot be imported in QGIS 3.x.\n' \
              'Use {} or the version independent {} import instead.'.format(
                  name.replace('PyQt4', 'PyQt5'), name.replace('PyQt4', 'qgis.PyQt'))
        raise ImportError(msg)
    mod = _builtin_import(name, globals, locals, fromlist, level)

    if mod and '__file__' in mod.__dict__:
        module_name = mod.__name__ if fromlist else name
        package_name = module_name.split('.')[0]
        # check whether the module belongs to one of our plugins
        if package_name in available_plugins:
            if package_name not in _plugin_modules:
                _plugin_modules[package_name] = set()
            _plugin_modules[package_name].add(module_name)
            # check the fromlist for additional modules (from X import Y,Z)
            if fromlist:
                for fromitem in fromlist:
                    frmod = module_name + "." + fromitem
                    if frmod in sys.modules:
                        _plugin_modules[package_name].add(frmod)

    return mod


if not os.environ.get('QGIS_NO_OVERRIDE_IMPORT'):
    if _uses_builtins:
        builtins.__import__ = _import
    else:
        __builtin__.__import__ = _import


def run_script_from_file(filepath):
    """
    Runs a Python script from a given file. Supports loading processing scripts.
    :param filepath: The .py file to load.
    """
    import sys
    import inspect
    from qgis.processing import alg
    try:
        from qgis.core import QgsApplication, QgsProcessingAlgorithm, QgsProcessingFeatureBasedAlgorithm
        from processing.gui.AlgorithmDialog import AlgorithmDialog
        _locals = {}
        exec(open(filepath.replace(
            "\\\\", "/").encode(sys.getfilesystemencoding())).read(), _locals)
        alginstance = None
        try:
            alginstance = alg.instances.pop().createInstance()
        except IndexError:
            for name, attr in _locals.items():
                if inspect.isclass(attr) and issubclass(attr, (QgsProcessingAlgorithm, QgsProcessingFeatureBasedAlgorithm)) and attr.__name__ not in ("QgsProcessingAlgorithm", "QgsProcessingFeatureBasedAlgorithm"):
                    alginstance = attr()
                    break
        if alginstance:
            alginstance.setProvider(
                QgsApplication.processingRegistry().providerById("script"))
            alginstance.initAlgorithm()
            dlg = AlgorithmDialog(alginstance)
            dlg.show()
    except ImportError:
        pass
