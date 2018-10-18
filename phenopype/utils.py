# -*- coding: utf-8 -*-
"""
Last Update: 2018/10/02
Version 0.4.0
@author: Moritz Lürig
"""

import cv2
import numpy as np
import exifread
from collections import Counter

#%%
green = (0, 255, 0)
red = (0, 0, 255)
blue = (255, 0, 0)
black = (0,0,0)
white = (255,255,255)

#%% helper functions

def exif_date(path): 
    f = open(path, 'rb')
    tags = exifread.process_file(f)
    t = str(tags["EXIF DateTimeOriginal"])
    return t[0:4] + "-" + t[5:7] + "-" + t[8:10] + " " + t[11:20]

def blur(image, blur_kern):
    kern = np.ones((blur_kern,blur_kern))/(blur_kern**2)
    ddepth = -1
    return cv2.filter2D(image,ddepth,kern)

def gray_scale(source, **kwargs):
    img = source
    if "resize" in kwargs:
        img = cv2.resize(img, (0,0), fx=1*kwargs.get("resize"), fy=1*kwargs.get("resize")) 
    vec = np.ravel(img)
    mc = Counter(vec).most_common(9)
    g = [item[0] for item in mc]
    return int(np.median(g))
