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


class CallbackNodeBase(plugins.DependNode):
    call_name = os.getenv("__MAYA_CALLBACK_FUNC__") or "__callback__"
    _name = PLUGIN_NAME
    # _typeId = OpenMaya.MTypeId(0x00991)

    enable = OpenMaya.MObject()
    script = OpenMaya.MObject()
    inputs = OpenMaya.MObject()
    outputs = OpenMaya.MObject()
    sync_group = OpenMaya.MObject()

    listen_title = OpenMaya.MObject()
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

        cls.listen_title = tAttr.create("listen_title", "lt", kString)
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
        cAttr.addChild(cls.listen_title)
        cAttr.addChild(cls.listen_enable)
        cAttr.addChild(cls.listen_script)
        cAttr.addChild(cls.listen_inputs)
        cAttr.setArray(1)

        cls.addAttribute(cls.sync_group)
        cls.addAttribute(cls.listen_group)

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

    def on_element_changed(self, plug, other_plug, plug_dict):
        grp = plug.array().parent()
        grp_index = grp.logicalIndex()
        index = plug.logicalIndex()
        if self.is_connection_made:
            plug_dict[grp_index][index] = other_plug.name()
        elif self.is_connection_broken:
            plug_dict[grp_index].pop(index, None)


class CallbackNodeSyncMixin(object):
    def __init__(self):
        super(CallbackNodeSyncMixin, self).__init__()
        self.sync_cache = {}
        self.sync_inputs_plugs = nestdict()
        self.sync_outputs_plugs = nestdict()

    def eval_sync_grp(self, grp, call_type):
        index = grp.logicalIndex()
        is_enable = grp.child(self.enable).asBool()
        if not is_enable:
            return

        module = self.sync_cache.get(index)
        scirpt_plug_name = grp.child(self.script).name()
        callback = getattr(module, self.call_name, None)

        inputs = self.sync_inputs_plugs.get(index)
        outputs = self.sync_outputs_plugs.get(index)
        try:
            assert module, "`%s` not valid" % scirpt_plug_name
            assert callable(callback), "`%s` -> `%s` method not exists" % (
                scirpt_plug_name,
                self.call_name,
            )
            assert inputs, "`%s` is empty" % grp.child(self.inputs).name()
            assert outputs, "`%s` is empty" % grp.child(self.outputs).name()

        except AssertionError as e:
            is_eval = call_type == "eval"
            if is_eval:
                OpenMaya.MGlobal.displayWarning(str(e))
            return

        data = {}
        data["inputs"] = [i for _, i in sorted(inputs.items())]
        data["outputs"] = [o for _, o in sorted(outputs.items())]
        data["type"] = call_type
        # NOTE ignore undo run callback
        cmds.evalDeferred(partial(Util.ignore_undo_deco(callback), self, data))


class CallbackNodeListenMixin(object):
    def __init__(self):
        super(CallbackNodeListenMixin, self).__init__()
        self.listen_cache = {}
        self.listen_inputs_plugs = nestdict()
        self.listen_ids = {}

    def on_listen_attr_changed(self, msg, plug, other_plug=None, grp=None):
        is_enable = grp.child(self.listen_enable).asBool()
        if not is_enable:
            return

        index = grp.logicalIndex()
        scirpt_plug_name = grp.child(self.listen_script).name()

        try:
            module = self.listen_cache.get(index)
            assert module, "`%s` not valid" % scirpt_plug_name
            callback = getattr(module, self.call_name, None)
            assert callable(callback), "`%s` -> `%s` method not exists" % (
                scirpt_plug_name,
                self.call_name,
            )
        except AssertionError as e:
            OpenMaya.MGlobal.displayWarning(str(e))
            return

        callback(self, msg, plug, other_plug)

    def on_listen_connect(self, plug, other_plug):
        grp = plug.array().parent()
        index = grp.logicalIndex()

        if self.is_connection_made:
            callback_id = OpenMaya.MNodeMessage.addAttributeChangedCallback(
                other_plug.node(), self.on_listen_attr_changed, grp
            )
            self.listen_ids[index] = callback_id
        elif self.is_connection_broken:
            callback_id = self.listen_ids[index]
            OpenMaya.MMessage.removeCallback(callback_id)


class CallbackNode(
    CallbackNodeSyncMixin,
    CallbackNodeListenMixin,
    CallbackNodeBase,
):
    def on_attr_changed(self, msg, plug, other_plug=None, data=None):

        self.is_connection_made = msg & OpenMaya.MNodeMessage.kConnectionMade
        self.is_connection_broken = msg & OpenMaya.MNodeMessage.kConnectionBroken

        is_attribute_set = msg & OpenMaya.MNodeMessage.kAttributeSet
        is_array_added = msg & OpenMaya.MNodeMessage.kAttributeArrayAdded

        attribute = plug.attribute()
        if is_attribute_set:
            if attribute == self.script:
                return self.on_script_changed(plug, self.sync_cache)
            elif attribute == self.listen_script:
                return self.on_script_changed(plug, self.listen_cache)
        elif self.is_connection_made or self.is_connection_broken:
            plug_dict = None
            if attribute == self.inputs:
                plug_dict = self.sync_inputs_plugs
            elif attribute == self.outputs:
                plug_dict = self.sync_outputs_plugs
            elif attribute == self.listen_inputs:
                plug_dict = self.listen_inputs_plugs
                self.on_listen_connect(plug, other_plug)

            if plug_dict is not None:
                return self.on_element_changed(plug, other_plug, plug_dict)
        elif is_array_added:
            # NOTE new plug auto add title attribute
            if attribute == self.listen_group:
                index = plug.logicalIndex()
                title_plug = plug.child(self.listen_title)
                title_plug.setString("Listen Group %s" % index)

    def on_node_removed(self, *args):
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

        # # NOTE setup default listen_title name
        # plug = OpenMaya.MPlug(this, self.listen_group)
        # plug = plug.elementByLogicalIndex(0).child(self.listen_title)
        # plug.setString("Listen Group 0")

    def setDependentsDirty(self, plug, _):
        filter_attrs = [
            self.enable,
            self.script,
            self.listen_enable,
            self.listen_script,
            self.listen_title,
            self.listen_inputs,
        ]

        call_type = "eval"
        if self.is_connection_made:
            call_type = "make_connection"
            self.is_connection_made = False
        else:
            filter_attrs.append(self.outputs)

        if self.is_connection_broken:
            call_type = "broke_connection"
            self.is_connection_broken = False

        attribute = plug.attribute()
        if attribute in filter_attrs:
            return

        # NOTE refresh message attribute
        cmds.evalDeferred(partial(cmds.dgdirty, plug.name(), c=1))

        if plug.isElement():
            grp = plug.array().parent()
            if grp == self.sync_group:
                self.eval_sync_grp(grp, call_type)

def initializePlugin(mobject):
    CallbackNode.register(mobject)


def uninitializePlugin(mobject):
    CallbackNode.deregister(mobject)


if __name__ == "__main__":
    from textwrap import dedent

    cmds.delete(cmds.ls(type=PLUGIN_NAME))
    cmds.delete(cmds.ls(type="floatConstant"))
    cmds.flushUndo()
    if cmds.pluginInfo(PLUGIN_NAME, q=1, loaded=1):
        cmds.unloadPlugin(PLUGIN_NAME)
    cmds.loadPlugin(__file__)

    node = cmds.createNode(PLUGIN_NAME)
    float_constant = cmds.createNode("floatConstant")
    cmds.connectAttr(float_constant + ".outFloat", node + ".sg[0].i[0]", f=1)
    float_constant = cmds.createNode("floatConstant")
    cmds.connectAttr(float_constant + ".inFloat", node + ".sg[0].o[0]", f=1)
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
    # node = "callbackNode1"
    cmds.setAttr(node + ".sg[0].s", code, typ="string")
