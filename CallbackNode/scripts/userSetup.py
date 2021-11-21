# -*- coding: utf-8 -*-
"""
auto load UIBot plugin
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

__author__ = "timmyliang"
__email__ = "820472580@qq.com"
__date__ = "2021-10-20 21:35:43"

import os
from maya import cmds


MODULE_NAME = "CallbackNode"

def initialize():
    module_path = cmds.getModulePath(mn=MODULE_NAME)
    plugin_path = os.path.join(module_path, "plug-ins", "%s.py" % MODULE_NAME)
    if os.path.isfile(plugin_path):
        if not cmds.pluginInfo(plugin_path, q=1, loaded=1):
            cmds.loadPlugin(plugin_path)


if __name__ == "__main__":
    if not cmds.about(q=1, batch=1):
        cmds.evalDeferred(initialize, lp=1)
