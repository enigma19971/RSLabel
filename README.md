#	RSLabel

##	RSLabel is a **Remote sensing image label tool.**


![markdown](https://github.com/enigma19971/RSLabel/blob/master/pic1.PNG "markdown")


##	How to Run it
this project is based on **labeme** ,PyQT5 and pygdal.   so the python3.6 env must be download and installed in the current folder.
you can using annaconda to download the python3.6 env and install PyQT5, gdal youself, and put it in the current folder
![Python Env](https://github.com/enigma19971/RSLabel/blob/master/python.PNG "like that")

we provide a package 

[python3.7 + PyGdal + PyQT5](https://pan.baidu.com/s/1yZVESoRWEvgQP1MO1l8xiA),the extraction code is **3crv**

After you download it and unzip to your root folder. you can run the RSLabel.exe

or you can download the binary from here
[rslabel-install](https://pan.baidu.com/s/1fF3hUzCLY66XrXVFHENQEQ )   the extraction code is **lpps**

##  get started!
- build overviews for images.  
**for big images(larger than 300M), building overviews is highly recommended.**
![](https://github.com/enigma19971/RSLabel/blob/master/build-overview.PNG "build overview")

  you can chose build overviews for single file or a folder
- open the selected folder or a file
- begin to draw or edit the polygon using toolbar buttons
![](https://github.com/enigma19971/RSLabel/blob/master/editing.PNG "polygon")
- when **drawing**, you can use **right click** to revoke the last point
- when **paning**, the **draw** and **edit** action are disabled.
- when **drawing** or **editing**, you can press **CTRL** button and drag the mouse to pan

##	features
-	Support 32bit and 16bit RS IMAGE. 
![](https://github.com/enigma19971/RSLabel/blob/master/16bit.PNG "scalar remap")
>	display single 16bit image with scalar remapping
![](https://github.com/enigma19971/RSLabel/blob/master/pseudo-colour.png "pseudo-colour")
>	display single 16bit image with pseudo-colour
-	Fully compatible with LabelMe operating methods and provide other utilities to do with remote sensing image.
![](https://github.com/enigma19971/RSLabel/blob/master/labelme_utilities.PNG "labelme compatible")
-	Support Very large RS IMAGE
-	Supporting infinite zooming

##	the slant rectangle
this tool is very convinient to label object with an angle. look that
![](https://github.com/enigma19971/RSLabel/blob/master/slantRect.PNG "build overview")

##	export the result as VOC , COCO or yolo format
you can export the result as VOC ,COCO or yolo dataset's format , and use tensorflow or other deep learning framework to train the data.
![](https://github.com/enigma19971/RSLabel/blob/master/exportas.PNG "export as VOC")




##	contact us
weixin  714601476
