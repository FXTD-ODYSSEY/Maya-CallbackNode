# -*- coding: utf-8 -*-
"""
https://sonictk.github.io/maya_node_callback_example/
Callback Node for dynamic update value without connections

__MAYA_CALLBACK_FUNC__ | default is `__callback__`
customize the callback function name 
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

__author__ = "timmyliang"
__email__ = "820472580@qq.com"
__date__ = "2021-11-20 21:49:35"

import os
import sys
import ast
import imp
from collections import defaultdict
from functools import partial
from string import Template

from maya import cmds
from maya import OpenMaya
from pymel.api import plugins
from pymel import core as pm

import six


PLUGIN_NAME = "CallbackNode"
CALLBACK_NAME = os.getenv("__MAYA_CALLBACK_FUNC__") or "__callback__"
__file__ = globals().get("__file__")
__file__ = __file__ or cmds.pluginInfo(PLUGIN_NAME, q=1, p=1)
DIR = os.path.dirname(os.path.abspath(__file__))
nestdict = lambda: defaultdict(nestdict)


class Util:
    @staticmethod
    def is_valid_python(code):
        """
        https://stackoverflow.com/a/11854793
        """
        try:
            ast.parse(code)
        except SyntaxError:
            return False
        return True

    @staticmethod
    def ignore_undo_deco(func):
        def wrapper(*args, **kwargs):
            cmds.undoInfo(swf=0)
            res = func(*args, **kwargs)
            cmds.undoInfo(swf=1)
            return res

        return wrapper

    @staticmethod
    def get_array_element(plugs):
        outputs = []
        for i in range(plugs.numConnectedElements()):
            plug = plugs.elementByPhysicalIndex(i)
            array = OpenMaya.MPlugArray()
            plug.connectedTo(array, True, False)
            outputs.append(array[0])
            del array
        return outputs


class CallbackNodeBase(plugins.DependNode):

    enable = OpenMaya.MObject()
    script = OpenMaya.MObject()
    inputs = OpenMaya.MObject()
    outputs = OpenMaya.MObject()
    sync_group = OpenMaya.MObject()

    listen_label = OpenMaya.MObject()
    listen_enable = OpenMaya.MObject()
    listen_script = OpenMaya.MObject()
    listen_inputs = OpenMaya.MObject()
    listen_group = OpenMaya.MObject()

    @classmethod
    def initialize(cls):

        eAttr = OpenMaya.MFnEnumAttribute()
        msgAttr = OpenMaya.MFnMessageAttribute()
        cAttr = OpenMaya.MFnCompoundAttribute()
        tAttr = OpenMaya.MFnTypedAttribute()
        kString = OpenMaya.MFnData.kString
        cls.enable = eAttr.create("enable", "e", 1)
        eAttr.addField("off", 0)
        eAttr.addField("on", 1)
        eAttr.setKeyable(1)
        eAttr.setWritable(1)

        cls.script = tAttr.create("script", "s", kString)
        tAttr.setWritable(1)

        cls.inputs = msgAttr.create("inputs", "i")
        msgAttr.setArray(1)
        msgAttr.setWritable(1)
        msgAttr.setStorable(1)

        cls.outputs = msgAttr.create("outputs", "o")
        msgAttr.setArray(1)
        msgAttr.setWritable(1)
        msgAttr.setStorable(1)

        cls.sync_group = cAttr.create("sync_group", "sg")
        cAttr.addChild(cls.enable)
        cAttr.addChild(cls.script)
        cAttr.addChild(cls.inputs)
        cAttr.addChild(cls.outputs)
        cAttr.setArray(1)

        # -----------------------------------------------------------

        cls.listen_label = tAttr.create("listen_label", "ll", kString)
        tAttr.setWritable(1)

        cls.listen_enable = eAttr.create("listen_enable", "le", 1)
        eAttr.addField("off", 0)
        eAttr.addField("on", 1)
        eAttr.setKeyable(1)
        eAttr.setWritable(1)

        cls.listen_script = tAttr.create("listen_script", "ls", kString)
        tAttr.setWritable(1)

        cls.listen_inputs = msgAttr.create("listen_inputs", "li")
        msgAttr.setArray(1)
        msgAttr.setWritable(1)
        msgAttr.setStorable(1)

        cls.listen_group = cAttr.create("listen_group", "lg")
        cAttr.addChild(cls.listen_label)
        cAttr.addChild(cls.listen_enable)
        cAttr.addChild(cls.listen_script)
        cAttr.addChild(cls.listen_inputs)
        cAttr.setArray(1)

        cls.addAttribute(cls.sync_group)
        cls.addAttribute(cls.listen_group)
        # TODO selection change callback

    def __init__(self):
        super(CallbackNodeBase, self).__init__()
        self.is_connection_made = False
        self.is_connection_broken = False
        self.callback_ids = OpenMaya.MCallbackIdArray()

    def on_script_changed(self, plug, cache, module_name="__CallbackCache[{i}]__"):
        assert isinstance(cache, dict), "wrong type argument"

        grp = plug.parent()
        index = grp.logicalIndex()
        script = plug.asString()
        if not script:
            return

        module_name = module_name.format(i=index)

        envs = os.environ.copy()
        envs.update({"__file__": __file__, "__dir__": DIR})
        path = Template(script).substitute(envs)
        path = os.path.abspath(path)
        module = None
        if os.path.isfile(path):
            module = imp.load_source(module_name, path)
        elif Util.is_valid_python(script):
            module = imp.new_module(module_name)
            six.exec_(script, module.__dict__)

        if module:
            cache[index] = module
        else:
            OpenMaya.MGlobal.displayWarning("`%s` not valid" % plug.name())


class CallbackNodeSyncMixin(object):
    def __init__(self):
        super(CallbackNodeSyncMixin, self).__init__()
        self.sync_cache = {}
        self.deffer_flag = set()

    def eval_sync_grp(self, plug, call_type):
        grp = plug.array().parent()
        index = grp.logicalIndex()
        is_enable = grp.child(self.enable).asBool()
        if not is_enable:
            return

        module = self.sync_cache.get(index)
        scirpt_plug_name = grp.child(self.script).name()
        callback = getattr(module, CALLBACK_NAME, None)

        inputs = Util.get_array_element(grp.child(self.inputs))
        outputs = Util.get_array_element(grp.child(self.outputs))

        try:
            assert module, "`%s` not valid" % scirpt_plug_name
            assert callable(callback), "`%s` -> `%s` method not exists" % (
                scirpt_plug_name,
                CALLBACK_NAME,
            )
            assert inputs, "`%s` is empty" % grp.child(self.inputs).name()
            assert outputs, "`%s` is empty" % grp.child(self.outputs).name()

        except AssertionError as e:
            is_eval = call_type == "eval"
            if is_eval:
                OpenMaya.MGlobal.displayWarning(str(e))
            return

        data = {}
        data["inputs"] = [i.name() for i in inputs]
        data["outputs"] = [o.name() for o in outputs]
        data["type"] = call_type

        # NOTE ignore undo run callback
        callback = Util.ignore_undo_deco(callback)

        # TODO callback dead loop detect
        callback(self, data)
        # NOTE defer run so that sync the value properly
        if not self.deffer_flag:
            self.deffer_flag.add(1)
            cmds.evalDeferred(
                # NOTE exists check so that delete will perform correctly
                lambda p=plug.name(): (
                    cmds.objExists(p) and callback(self, data),
                    self.deffer_flag.clear(),
                )
            )


class CallbackNodeListenMixin(object):
    def __init__(self):
        super(CallbackNodeListenMixin, self).__init__()
        self.listen_cache = {}
        self.listen_inputs_plugs = nestdict()
        self.listen_ids = {}
        self.listen_nodes = defaultdict(list)

    def on_listen_attr_changed(self, msg, plug, other_plug=None, grp=None):
        is_enable = grp.child(self.listen_enable).asBool()
        if not is_enable:
            return

        index = grp.logicalIndex()
        scirpt_plug_name = grp.child(self.listen_script).name()

        try:
            module = self.listen_cache.get(index)
            assert module, "`%s` not valid" % scirpt_plug_name
            callback = getattr(module, CALLBACK_NAME, None)
            assert callable(callback), "`%s` -> `%s` method not exists" % (
                scirpt_plug_name,
                CALLBACK_NAME,
            )
        except AssertionError as e:
            OpenMaya.MGlobal.displayWarning(str(e))
            return

        Util.ignore_undo_deco(callback)(self, msg, plug, other_plug)

    def on_listen_connect(self, plug, other_plug):
        grp = plug.array().parent()
        index = grp.logicalIndex()
        node = other_plug.node()
        listen_nodes = self.listen_nodes[index]
        if self.is_connection_made:
            if node in listen_nodes:
                name = OpenMaya.MFnDependencyNode(node).name()
                OpenMaya.MGlobal.displayWarning("`%s` node already listened" % name)
                return

            listen_nodes.append(node)
            callback_id = OpenMaya.MNodeMessage.addAttributeChangedCallback(
                node, self.on_listen_attr_changed, grp
            )
            self.listen_ids[index] = callback_id
        elif self.is_connection_broken:
            if node in listen_nodes:
                listen_nodes.remove(node)
            callback_id = self.listen_ids.get(index)
            if callback_id is not None:
                OpenMaya.MMessage.removeCallback(callback_id)


class CallbackNode(CallbackNodeSyncMixin, CallbackNodeListenMixin, CallbackNodeBase):
    # NOTES(timmyliang) pymel auto setup this
    # _name = PLUGIN_NAME
    # _typeId = OpenMaya.MTypeId(0x00991)

    # def __init__(self):
    #     super(CallbackNode, self).__init__()

    def on_attr_changed(self, msg, plug, other_plug=None, data=None):

        # TODO state no effect

        self.is_connection_made = msg & OpenMaya.MNodeMessage.kConnectionMade
        self.is_connection_broken = msg & OpenMaya.MNodeMessage.kConnectionBroken

        is_attribute_set = msg & OpenMaya.MNodeMessage.kAttributeSet

        attribute = plug.attribute()
        if is_attribute_set:
            if attribute == self.script:
                return self.on_script_changed(plug, self.sync_cache)
            elif attribute == self.listen_script:
                return self.on_script_changed(plug, self.listen_cache)
        elif self.is_connection_made or self.is_connection_broken:
            if attribute == self.listen_inputs:
                self.on_listen_connect(plug, other_plug)

    def on_node_removed(self, *args):
        # TODO undo would not rebuild callbacks that make everything undesired
        OpenMaya.MMessage.removeCallbacks(self.callback_ids)
        for i in self.listen_ids.keys():
            OpenMaya.MMessage.removeCallback(i)

    def postConstructor(self):
        this = self.thisMObject()
        addAttributeChangedCallback = OpenMaya.MNodeMessage.addAttributeChangedCallback
        addNodePreRemovalCallback = OpenMaya.MNodeMessage.addNodePreRemovalCallback
        callback_id = addAttributeChangedCallback(this, self.on_attr_changed)
        self.callback_ids.append(callback_id)
        callback_id = addNodePreRemovalCallback(this, self.on_node_removed)
        self.callback_ids.append(callback_id)

    def setDependentsDirty(self, plug, _):
        # TODO state no effect

        attrs = [self.inputs]

        call_type = "eval"
        if self.is_connection_made:
            call_type = "make_connection"
            self.is_connection_made = False
            attrs.append(self.outputs)

        if self.is_connection_broken:
            call_type = "broke_connection"
            self.is_connection_broken = False

        attribute = plug.attribute()
        if attribute not in attrs:
            return

        # NOTE refresh message attribute
        # NOTE https://around-the-corner.typepad.com/adn/2012/07/dirtying-a-maya-mplug-for-array-attribute.html
        # cmds.evalDeferred(lambda p=plug.name(): cmds.dgdirty(p, c=1))
        cmds.dgdirty(plug.name(), c=1)

        if plug.isElement():
            grp = plug.array().parent()
            if grp == self.sync_group:
                self.eval_sync_grp(plug, call_type)


# TODO Node UI template

def initializePlugin(mobject):
    CallbackNode.register(mobject)
    sys.modules.setdefault("CallbackNode", imp.load_source("CallbackNode", __file__))


def uninitializePlugin(mobject):
    CallbackNode.deregister(mobject)
    sys.modules.pop("CallbackNode", None)


if __name__ == "__main__":
    from textwrap import dedent

    cmds.delete(cmds.ls(type=PLUGIN_NAME))
    cmds.delete(cmds.ls(type="floatConstant"))
    cmds.flushUndo()
    if cmds.pluginInfo(PLUGIN_NAME, q=1, loaded=1):
        cmds.unloadPlugin(PLUGIN_NAME)
    cmds.loadPlugin(__file__)

    callback_node = cmds.createNode(PLUGIN_NAME)
    float_constant = cmds.createNode("floatConstant")
    cmds.connectAttr(float_constant + ".outFloat", callback_node + ".sg[0].i[0]", f=1)
    float_constant = cmds.createNode("floatConstant")
    cmds.connectAttr(float_constant + ".inFloat", callback_node + ".sg[0].o[0]", f=1)
    code = dedent(
        """
        import pymel.core as pm
        def __callback__(self,data):
            inputs = data["inputs"]
            outputs = data["outputs"]
            src = pm.PyNode(inputs[0])
            dst = pm.PyNode(outputs[0])
            val = src.get()
            dst.set(val)
        """
    )
    cmds.setAttr(callback_node + ".sg[0].s", code, typ="string")
