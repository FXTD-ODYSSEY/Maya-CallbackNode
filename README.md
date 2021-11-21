# Maya-CallbackNode

Autodesk Maya Python CallbackNode for rigging and more

This idea is come from this [link](https://sonictk.github.io/maya_node_callback_example/)
Try to utilize the `OpenMaya` Event Callback to enhance rigging circumstances like IK/FK switch and more.

I have a similar idea When I watch a IK/FK swtich tutorial which using `scriptjob` for auto swtich.
But [cult of rig](http://www.cultofrig.com/2017/07/22/pilot-season-day-16-automatically-loading-callbacks-scene-load/) article just further more than that.
combinate the OpenMaya and `scirptNode` together, which make switch more powerful. 
[sonictk](https://sonictk.github.io/maya_node_callback_example/) claim that scriptNode not support the reference namespace circumstances.
So he make a C++ Node to register the related event, here is the [repo](https://github.com/sonictk/maya_node_callback_example)

sonictk Solution is great, but written by C++ which is hard to extend.
So I decide to create a Python OpenMaya Node and make it support run custom code in the string attribute.


