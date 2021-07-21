#%% modules
import cv2, copy
import numpy as np
import pandas as pd

from dataclasses import dataclass
from math import sqrt as _sqrt
import numpy.ma as ma

from phenopype.settings import AttrDict, colours, flag_verbose, _image_viewer_arg_list
from phenopype.utils_lowlevel import _auto_text_width, _auto_text_size, \
    _convert_arr_tup_list, _equalize_histogram, _resize_image, \
    _ImageViewer, _DummyClass
import phenopype.core.segmentation as segmentation

#%% functions


def blur(
    image,
    kernel_size=5,
    method="averaging",
    sigma_color=75,
    sigma_space=75,
    **kwargs
):
    """
    Apply a blurring algorithm to an image.

    Parameters
    ----------
    image: array 
        input image to be blurred
    kernel_size: int, optional
        size of the blurring kernel (has to be odd - even numbers will be ceiled)
    method: {averaging, gaussian, median, bilateral} str, optional
        blurring algorithm
    sigma_colour: int, optional
        for 'bilateral'
    sigma_space: int, optional
        for 'bilateral'

    Returns
    -------
    image : array 

    """
    ## checks
    if kernel_size % 2 == 0:
        kernel_size = kernel_size + 1
        if flag_verbose:
            print("even kernel_size supplied - need odd kernel_size")
            
    ## method
    if method == "averaging":
        blurred = cv2.blur(image, (kernel_size, kernel_size))
    elif method == "gaussian":
        blurred = cv2.GaussianBlur(image, (kernel_size, kernel_size), 0)
    elif method == "median":
        blurred = cv2.medianBlur(image, kernel_size)
    elif method == "bilateral":
        blurred = cv2.bilateralFilter(image, kernel_size, sigma_color, sigma_space)

    ## return
    return blurred


def create_mask(
    image,
    tool="rectangle",
    **kwargs
):

    ## convert previous annotations to 
    if "previous_annotation" in kwargs:
        previous_annotation = kwargs.get("previous_annotation")
        previous = {}            
        previous.update(previous_annotation["settings"])
        previous["polygons"] = previous_annotation["data"]["coord_list"]
        previous = _DummyClass(previous)    
        kwargs.update({"previous": previous})
                               
    ## retrieve and save settings
    settings = locals()
    for rm in ["image","include",
               "kwargs","key","value",
               "_image_viewer_params"]:
        settings.pop(rm, None)
        
    ## retrieve settings for image viewer
    _image_viewer_params = {}
    for key, value in kwargs.items():
        if key in _image_viewer_arg_list:
            settings[key] = value
            _image_viewer_params[key] = value

    ## draw masks
    out = _ImageViewer(image=image, 
                        tool=tool, 
                        **_image_viewer_params)
    if not out.done:
        print("- didn't finish: redo mask")
        return 
        
    # conversion and return
    if out.polygons is not None:
        coords = out.polygons

        annotation = {
            "info": {
                "annotation_type": "mask",
                "mask_shape": tool,
                "pp_function": "mask_manual",
            },
            "settings": settings,
            "data": {
                "n_shapes": len(coords),
                "coord_list": coords,
            }
        }
        return annotation
    else:
        print("- zero coordinates: redo mask")
        return 
    
    
def detect_mask(
    image,
    shape="circle",
    resize=1,
    dp=1,
    min_dist=50,
    param1=200,
    param2=100,
    min_radius=0,
    max_radius=0,
    verbose=True,
    **kwargs
):
    """
    Detect circles in grayscale image using Hough-Transform. Results can be 
    returned either as mask or contour
    
    Parameters
    ----------


    Returns
    -------
    
    """

    ## checks
    if len(image.shape) == 3:
        image = select_channel(image)
    image_resized = _resize_image(image, resize)
            
    ## settings
    settings = locals()
    for rm in ["image","resized"]:
        settings.pop(rm, None)
        
    ## method
    if shape=="circle":
        circles = cv2.HoughCircles(image_resized, 
                                   cv2.HOUGH_GRADIENT, 
                                   dp=max(int(dp*resize),1), 
                                   minDist=int(min_dist*resize),
                                   param1=int(param1*resize), 
                                   param2=int(param2*resize),
                                   minRadius=int(min_radius*resize), 
                                   maxRadius=int(max_radius*resize))
    
        ## output conversion
        if circles is not None:
            coords = []
            for idx, circle in enumerate(circles[0]):
                x,y,radius = circle/resize
                mask = np.zeros(image.shape[:2], dtype=np.uint8)
                mask = cv2.circle(mask, (x,y), radius, 255, -1)
                mask_contours = segmentation.detect_contours(
                    mask,
                    retrieval="ext", 
                    approximation="KCOS", 
                    verbose=False,
                    )
                coords.append(
                    np.append(
                        mask_contours["data"]["coords"][0],
                        [mask_contours["data"]["coords"][0][0]],
                        axis=0
                        )
                    )
            if verbose:
                print("Found {} circles".format(len(circles[0])))
        else:
            if verbose:
                print("No circles detected")
            return None
        
    ## return results
    annotation = {
        "info": {
            "annotation_type": "mask",
            "pp_function": "mask_detect",
        },
        "settings": settings,
        "data": {
            "n_shapes": len(coords),
            "coord_list": coords,
        }
    }
    return annotation
        
    

def create_reference(
    image,
    mask=False,
    overwrite=False,
    template=False,
    **kwargs
):
    """
    Measure a size or colour reference card. Minimum input interaction is 
    measuring a size reference: click on two points inside the provided image, 
    and enter the distance - returns the pixel-to-mm-ratio as integer or 
    inserts it into a provided DataFrame (df_image_data). In an optional second
    step, drag a rectangle mask over the reference card to exclude it from any
    subsequent image segementation. The mask is exported as new DataFrame, OR, 
    if provided before, gets appended to an existing one (df_masks). The mask
    can also be stored as a template for automatic reference detection with the
    "detect_reference" function.

    Parameters
    ----------
    obj_input : array or container
        input object
    df_image_data : DataFrame, optional
        an existing DataFrame containing image metadata to add the reference 
        information to (pixel-to-mm-ratio)
    df_masks : DataFrame, optional
        an existing DataFrame containing masks to add the created mask to
    mask : bool, optional
        mask a reference card inside the image (returns a mask DataFrame)
    overwrite : bool, optional
        if a container is supplied, or when working from the pype, should any 
        exsting reference information (px-to-mm-ratio) or template be overwritten
    template: bool, optional
        should a template for reference detection be created. with an existing 
        template, phenopype can try to find a reference card in a given image,
        measure its dimensions, and adjust and colour space. automatically 
        creates and returns a mask DataFrame that can be added to an existing
        one
    kwargs: optional
        developer options

    Returns
    -------
    px_mm_ratio: int or container
        pixel to mm ratio - not returned if df_image_data is supplied
    df_image_data: DataFrame or container
        new or updated, containes reference information
    df_masks: DataFrame or container
        new or updated, contains mask information
    template: array or container
        template for reference card detection

    """

    ## kwargs    
    flags = AttrDict({"mask":mask,"template":template, "overwrite":overwrite})


    ## method
    out = _ImageViewer(image, tool="reference")
    
    points = out.reference_coords
    distance_px = _sqrt(
            ((points[0][0] - points[1][0]) ** 2)
            + ((points[0][1] - points[1][1]) ** 2)
        )
    
    out = _ImageViewer(image, tool="comment", display="Enter distance in mm:")
    entry = out.entry
    distance_mm = float(entry)
    px_mm_ratio = float(distance_px / distance_mm)

    ## create template for image registration
    if flags.template or flags.mask:
        out = _ImageViewer(image, tool="template")

        ## make template and mask
        template = image[
            out.rect_list[0][1] : out.rect_list[0][3],
            out.rect_list[0][0] : out.rect_list[0][2],
        ]
        coords = out.point_list

    ## return results
    annotation = {
        "info": {
            "annotation_type": "reference",
            "pp_function": "create_reference",
        },
        "data": {
            "coord_list": coords,
        }
    }
    return annotation

def detect_reference(
    obj_input,
    df_image_data=None,
    template=None,
    overwrite=False,
    equalize=False,
    min_matches=10,
    resize=1,
    px_mm_ratio_ref=None,
    df_masks=None,
):
    """
    Find reference from a template created with "create_reference". Image registration 
    is run by the "AKAZE" algorithm. Future implementations will include more 
    algorithms to select from. First, use "create_reference" with "template=True"
    and pass the template to this function. This happends automatically in the 
    low and high throughput workflow (i.e., when "obj_input" is a container, the 
    template image is contained within. Use "equalize=True" to adjust the 
    histograms of all colour channels to the reference image.
    
    AKAZE: http://www.bmva.org/bmvc/2013/Papers/paper0013/abstract0013.pdf

    Parameters
    -----------
    obj_input: array or container
        input for processing
    df_image_data : DataFrame, optional
        an existing DataFrame containing image metadata to add the reference 
        information to (pixel-to-mm-ratio)
    df_masks : DataFrame, optional
        an existing DataFrame containing masks to add the detected mask to
    template : array or container, optional
        reference image of reference
    equalize : bool, optional
        should the provided image be colour corrected to match the template 
        images' histogram
    min_matches : int, optional
       minimum key point matches for image registration
    resize: num, optional
        resize image to speed up detection process. default: 0.5 for 
        images with diameter > 5000px (WARNING: too low values may 
        result in poor detection performance or even crashes)
    overwrite : bool, optional
        overwrite existing reference_detected_px_mm_ratio in container
    px_mm_ratio_ref : int, optional
        pixel-to-mm-ratio of the template image

    Returns
    -------
    reference_detected_px_mm_ratio: int or container
        pixel to mm ratio of current image
    image: array or container
        if reference contains colour information, this is the corrected image
    df_masks: DataFrame or container
        contains mask coordinates to mask reference card within image from 
        segmentation algorithms
    """

    ## kwargs
    flag_overwrite = overwrite
    flag_equalize = equalize

    ## load image
    template_px_mm_ratio = None
    template_image = None
    if obj_input.__class__.__name__ == "ndarray":
        image = obj_input
        if df_image_data.__class__.__name__ == "NoneType":
            df_image_data = pd.DataFrame({"filename": "unknown"}, index=[0])
        else:
            if "template_px_mm_ratio" in df_image_data:
                template_px_mm_ratio = df_image_data["template_px_mm_ratio"]
                print("template_px_mm_ratio loaded")
        if df_masks.__class__.__name__ == "NoneType":
            df_masks = pd.DataFrame(columns=["mask", "include", "coords"])
    elif obj_input.__class__.__name__ == "container":
        image = copy.deepcopy(obj_input.image)
        df_image_data = obj_input.df_image_data
        if hasattr(obj_input, "reference_template_px_mm_ratio"):
            template_px_mm_ratio = obj_input.reference_template_px_mm_ratio
        if hasattr(obj_input, "reference_template_image"):
            template_image = obj_input.reference_template_image
        if hasattr(obj_input, "df_masks"):
            df_masks = copy.deepcopy(obj_input.df_masks)
        else:
            df_masks = pd.DataFrame(columns=["mask", "include", "coords"])

    ## check if all info has been provided
    while True:
        if any(
            [
                template_px_mm_ratio.__class__.__name__ == "NoneType",
                template_image.__class__.__name__ == "NoneType",
            ]
        ):
            print("- reference information missing - abort")
            break
        if hasattr(obj_input, "reference_detected_px_mm_ratio") and not flag_overwrite:
            detected_px_mm_ratio = obj_input.reference_detected_px_mm_ratio
            print("- reference already detected (overwrite=False)")
            break
        elif hasattr(obj_input, "reference_detected_px_mm_ratio") and flag_overwrite:
            print(" - detecting reference (overwriting)")
            pass

        ## if image diameter bigger than 5000 px, then automatically resize
        if (image.shape[0] + image.shape[1]) / 2 > 5000 and resize == 1:
            resize_factor = 0.5
            print(
                "large image - resizing by factor "
                + str(resize_factor)
                + " to avoid slow image registration"
            )
        else:
            resize_factor = resize
        image = cv2.resize(image, (0, 0), fx=1 * resize_factor, fy=1 * resize_factor)

        ## method
        akaze = cv2.AKAZE_create()
        kp1, des1 = akaze.detectAndCompute(template_image, None)
        kp2, des2 = akaze.detectAndCompute(image, None)
        matcher = cv2.DescriptorMatcher_create(cv2.DescriptorMatcher_BRUTEFORCE_HAMMING)
        matches = matcher.knnMatch(des1, des2, 2)

        # keep only good matches
        good = []
        for m, n in matches:
            if m.distance < 0.7 * n.distance:
                good.append(m)

        # find and transpose coordinates of matches
        if len(good) >= min_matches:
            ## find homography betweeen detected keypoints
            src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

            ## transform boundary box of template
            rect_old = np.array(
                [
                    [[0, 0]],
                    [[0, template_image.shape[0]]],
                    [[template_image.shape[1], template_image.shape[0]]],
                    [[template_image.shape[1], 0]],
                ],
                dtype=np.float32,
            )
            rect_new = cv2.perspectiveTransform(rect_old, M) / resize_factor

            # calculate template diameter
            rect_new = rect_new.astype(np.int32)
            (x, y), radius = cv2.minEnclosingCircle(rect_new)
            diameter_new = radius * 2

            # calculate transformed diameter
            rect_old = rect_old.astype(np.int32)
            (x, y), radius = cv2.minEnclosingCircle(rect_old)
            diameter_old = radius * 2

            ## calculate ratios
            diameter_ratio = diameter_new / diameter_old
            px_mm_ratio_new = round(diameter_ratio * template_px_mm_ratio, 1)

            ## add to image df
            df_image_data["current_px_mm_ratio"] = px_mm_ratio_new

            ## feedback
            print("---------------------------------------------------")
            print("Reference card found with %d keypoint matches:" % len(good))
            print("template image has %s pixel per mm." % (template_px_mm_ratio))
            print("current image has %s pixel per mm." % (px_mm_ratio_new))
            print("= %s %% of template image." % round(diameter_ratio * 100, 3))
            print("---------------------------------------------------")

            ## create mask from new coordinates
            coords = _convert_arr_tup_list(rect_new)
            coords.append(coords[0])
            if "reference" in df_masks["mask"].values:
                df_masks = df_masks[~df_masks["mask"].isin(["reference"])]
            row_reference = pd.DataFrame(
                {"mask": "reference", "include": False, "coords": str([coords])}, index=[0]
            )
            row_reference = pd.concat(
                [
                    pd.concat([df_image_data] * len(row_reference)).reset_index(drop=True),
                    row_reference.reset_index(drop=True),
                ],
                axis=1,
            )
            df_masks = df_masks.append(row_reference, sort=False)
            detected_px_mm_ratio = px_mm_ratio_new
            break
        else:
            ## feedback
            print("---------------------------------------------------")
            print("Reference card not found - %d keypoint matches:" % len(good))
            print('Setting "current reference" to None')
            print("---------------------------------------------------")
            detected_px_mm_ratio = None
            break

        ## merge with existing image_data frame
        df_image_data["current_px_mm_ratio"] = detected_px_mm_ratio

    # ## rectangle coords of reference in image
    # rect_new = eval(df_masks.loc[df_masks["mask"]=="reference", "coords"].reset_index(drop=True)[0])

    ## do histogram equalization
    if flag_equalize:
        detected_rect_mask = np.zeros(image.shape, np.uint8)
        cv2.fillPoly(detected_rect_mask, [np.array(rect_new)], colours["white"])
        (rx, ry, rw, rh) = cv2.boundingRect(np.array(rect_new))
        detected_rect_mask = ma.array(
            data=image[ry : ry + rh, rx : rx + rw],
            mask=detected_rect_mask[ry : ry + rh, rx : rx + rw],
        )
        image = _equalize_histogram(image, detected_rect_mask, template_image)
        print("histograms equalized")

    ## return
    if obj_input.__class__.__name__ == "ndarray":
        return df_image_data, df_masks, image
    elif obj_input.__class__.__name__ == "container":
        obj_input.df_image_data = df_image_data
        obj_input.df_masks = df_masks
        obj_input.reference_detected_px_mm_ratio = detected_px_mm_ratio
        if flag_equalize:
            obj_input.image_copy = image
            obj_input.image = image



def enter_data(
    image,
    df_image_data=None,
    field="ID",
    overwrite=False,
    **kwargs
):
    """
    Generic data entry that can be added as columns to an existing DataFrame. 
    Useful for images containing labels, or other comments. 

    Parameters
    ----------
    obj_input : array or container
        input object
    df_image_data : DataFrame, optional
        an existing DataFrame containing image metadata to add columns to
    columns : str or list
        columns to be added to existing or generic data frame
    overwrite : bool, optional
        overwrite existing columns in df
    fontsize : int, optional
        fonsize for onscreen display. 
    font_col : {"red", "green", "blue", "black", "white"} str, optional
        font colour for onscreen display. 

    Returns
    -------
    df_other_data: DataFrame or container
        contains the entered data

    """

    ## kwargs

    out = _ImageViewer(image, tool="comment")








def select_channel(image, channel="gray", invert=False):
    """
    Extract single channel from multi-channel array.

    Parameters
    ----------
    image : array
        input image
    channel : str, optional
        select specific image channel
    invert: false, bool
        invert all pixel intensities in image (e.g. 0 to 255 or 100 to 155)
    Returns
    -------
    image : TYPE
        DESCRIPTION.

    """
    
    if channel in ["grayscale","gray"]:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if channel in ["green","g",1]:
        image = image[:, :, 0]
    if channel in ["red", "r",2]:
        image = image[:, :, 1]
    if channel in ["blue","b",3]:
        image = image[:, :, 2]
    if channel == "raw":
        pass
    if flag_verbose:
        print("converted image to {} channel".format(str(channel)))
        
    if invert==True:
        image = cv2.bitwise_not(image)
        print("iverted image")
        
    return image


