import torch, cv2

import numpy.random as random
import numpy as np
import dataloaders.helpers as helpers
from dataloaders.skewed_axes_weight_map import *
from dataloaders.nellipse import *

class NEllipse(object):
    def __init__(self, is_val = True):
        self.is_val = is_val

    def __call__(self, sample):
        _target = sample['crop_gt']
        if np.max(_target) == 0:
            sample['nellipse'] = np.zeros(_target.shape, dtype=_target.dtype)
        else:
            if self.is_val == True:
                _points = extreme_points_fixed(_target, 0)
            else:
                _points = extreme_points(_target, 0)

            x_range = np.arange(_target.shape[0])
            y_range = np.arange(_target.shape[1])
            sample['nellipse'] = compute_nellipse(x_range, y_range, _points) * 255

        return sample


class NEllipseWithGaussians(object):
    def __init__(self, alpha = 0.6, is_val = True):
        self.alpha = alpha
        self.is_val = is_val
    def __call__(self, sample):
        _target = sample['crop_gt']
        if np.max(_target) == 0:
            sample['nellipseWithGaussians'] = np.zeros(_target.shape, dtype=_target.dtype)
        else:
            if self.is_val == True:
                _points = extreme_points_fixed(_target, 0)
            else:
                _points = extreme_points(_target, 0)
            x_range = np.arange(_target.shape[0])
            y_range = np.arange(_target.shape[1])
            z1, z2 = compute_nellipse_gaussianHM_fast(x_range, y_range, _points)
            z1 *= 255
            z2 *= 255
            z = z1 + z2 * self.alpha
            z *= (255.0/z.max())
            sample['nellipseWithGaussians'] = z
        return sample




def trainValMode(mode):
    global is_val
    if mode == 'train':
        is_val = False
    elif mode == 'val':
        is_val = True
    else:
        print("Please enter train or val mode")
        exit()


class CreateBBMask(object):
    def __call__(self, sample):
        msk = sample['gt']
        bbox = helpers.get_bbox(msk)
        out = np.ones(msk.shape) * 255
        out[bbox[1]: bbox[3], bbox[0]: bbox[2]] = 0
        sample['bb_mask'] = out.astype(np.float32)
        return sample

class ScaleNRotate(object):
    """Scale (zoom-in, zoom-out) and Rotate the image and the ground truth.
    Args:
        two possibilities:
        1.  rots (tuple): (minimum, maximum) rotation angle
            scales (tuple): (minimum, maximum) scale
        2.  rots [list]: list of fixed possible rotation angles
            scales [list]: list of fixed possible scales
    """
    def __init__(self, rots=(-30, 30), scales=(.75, 1.25), semseg=False):
        assert (isinstance(rots, type(scales)))
        self.rots = rots
        self.scales = scales
        self.semseg = semseg

    def __call__(self, sample):

        if type(self.rots) == tuple:
            # Continuous range of scales and rotations
            rot = (self.rots[1] - self.rots[0]) * random.random() - \
                  (self.rots[1] - self.rots[0])/2

            sc = (self.scales[1] - self.scales[0]) * random.random() - \
                 (self.scales[1] - self.scales[0]) / 2 + 1
        elif type(self.rots) == list:
            # Fixed range of scales and rotations
            rot = self.rots[random.randint(0, len(self.rots))]
            sc = self.scales[random.randint(0, len(self.scales))]
        process = True
        while process:
            process = False
            for elem in sample.keys():
                if 'id' in elem or 'meta' in elem:
                    continue

                tmp = sample[elem]

                h, w = tmp.shape[:2]
                center = (w / 2, h / 2)
                assert(center != 0)  # Strange behaviour warpAffine
                M = cv2.getRotationMatrix2D(center, rot, sc)
                if ((tmp == 0) | (tmp == 1) | (tmp == 255)).all():
                    flagval = cv2.INTER_NEAREST
                elif 'gt' in elem and self.semseg:
                    flagval = cv2.INTER_NEAREST
                else:
                    flagval = cv2.INTER_CUBIC
                if 'bb_mask' in elem:
                    tmp = cv2.warpAffine(tmp.astype(np.uint8), M, (w, h), flags=flagval, borderValue = 255)
                else:
                    tmp = cv2.warpAffine(tmp.astype(np.uint8), M, (w, h), flags=flagval)
                
                # if elem == 'gt':
                #     pts = extreme_points(tmp,0)
                #     try:
                #         _ = getPointOfIntersection(pts)
                #     except:
                #         # print("ERROR ENCOUNTERED AND HANDLED")
                #         # np.save('tmp.npy', tmp)
                #         print(sample['id'])
                #         process = True

                if not process: sample[elem] = tmp
        return sample

    def __str__(self):
        return 'ScaleNRotate:(rot='+str(self.rots)+',scale='+str(self.scales)+')'


class FixedResize(object):
    """Resize the image and the ground truth to specified resolution.
    Args:
        resolutions (dict): the list of resolutions
    """
    def __init__(self, resolutions=None, flagvals=None):
        self.resolutions = resolutions
        self.flagvals = flagvals
        if self.flagvals is not None:
            assert(len(self.resolutions) == len(self.flagvals))

    def __call__(self, sample):

        # Fixed range of scales
        if self.resolutions is None:
            return sample

        elems = list(sample.keys())

        for elem in elems:

            if 'crop_relax' in elem or 'meta' in elem or 'bbox' in elem or ('extreme_points_coord' in elem and elem not in self.resolutions):
                continue
            if 'extreme_points_coord' in elem and elem in self.resolutions:
                bbox = sample['bbox']
                crop_size = np.array([bbox[3]-bbox[1]+1, bbox[4]-bbox[2]+1])
                res = np.array(self.resolutions[elem]).astype(np.float32)
                sample[elem] = np.round(sample[elem]*res/crop_size).astype(np.int)
                continue
            if elem in self.resolutions:
                if self.resolutions[elem] is None:
                    continue
                if isinstance(sample[elem], list):
                    if sample[elem][0].ndim == 3:
                        output_size = np.append(self.resolutions[elem], [3, len(sample[elem])])
                    else:
                        output_size = np.append(self.resolutions[elem], len(sample[elem]))
                    tmp = sample[elem]
                    sample[elem] = np.zeros(output_size, dtype=np.float32)
                    for ii, crop in enumerate(tmp):
                        if self.flagvals is None:
                            sample[elem][..., ii] = helpers.fixed_resize(crop, self.resolutions[elem])
                        else:
                            sample[elem][..., ii] = helpers.fixed_resize(crop, self.resolutions[elem], flagval=self.flagvals[elem])
                else:
                    if self.flagvals is None:
                        sample[elem] = helpers.fixed_resize(sample[elem], self.resolutions[elem])
                    else:
                        sample[elem] = helpers.fixed_resize(sample[elem], self.resolutions[elem], flagval=self.flagvals[elem])
            else:
                del sample[elem]
        return sample

    def __str__(self):
        return 'FixedResize:'+str(self.resolutions)


class RandomHorizontalFlip(object):
    """Horizontally flip the given image and ground truth randomly with a probability of 0.5."""

    def __call__(self, sample):

        if random.random() < 0.5:
            for elem in sample.keys():
                if 'id' in elem or 'meta' in elem:
                    continue
                tmp = sample[elem]
                tmp = cv2.flip(tmp, flipCode=1)
                sample[elem] = tmp

        return sample

    def __str__(self):
        return 'RandomHorizontalFlip'


class ExtremePoints(object):
    """
    Returns the four extreme points (left, right, top, bottom) (with some random perturbation) in a given binary mask
    sigma: sigma of Gaussian to create a heatmap from a point
    pert: number of pixels fo the maximum perturbation
    elem: which element of the sample to choose as the binary mask
    """
    def __init__(self, sigma=10, pert=0, elem='gt', is_val = None):
        self.sigma = sigma
        self.pert = pert
        self.elem = elem
        self.is_val = is_val

    def __call__(self, sample):
        if sample[self.elem].ndim == 3:
            raise ValueError('ExtremePoints not implemented for multiple object per image.')
        _target = sample[self.elem]
        if np.max(_target) == 0:
            sample['extreme_points'] = np.zeros(_target.shape, dtype=_target.dtype) #  TODO: handle one_mask_per_point case
        else:
            if self.is_val == True:
                _points = extreme_points_fixed(_target, self.pert)
            elif self.is_val == False:
                _points = extreme_points(_target, self.pert)

            sample['extreme_points'] = helpers.make_gt(_target, _points, sigma=self.sigma, one_mask_per_point=False)

        return sample

    def __str__(self):
        return 'ExtremePoints:(sigma='+str(self.sigma)+', pert='+str(self.pert)+', elem='+str(self.elem)+')'

class AddConfidenceMap(object):
    def __init__(self, elem = 'image', hm_type = 'l1l2', tau = 1, pert = 0, is_val = None):
        self.elem = elem
        self.hm_type = hm_type
        self.tau = tau
        self.is_val = is_val
        self.pert = pert


    def __call__(self, sample):
        img = sample[self.elem]
        msk = sample['crop_gt'].astype(np.bool)
        # msk = ndimage.binary_fill_holes(msk)
        # extr_pts = sample['pts']

        if len(np.unique(msk)) == 1:
            hm = np.zeros(img.shape[:2])
        else:
            if self.hm_type == 'l1l2':
                # extr_pts, lines       = getSimulatedExtremePoints(msk, stdDevMultiplier=6, angle_perturb=False) # Included in the new modified file
                # plt.imshow(msk, cmap='gray')
                # plt.imshow(colorMaskWithAlpha(lines.astype(float)))
                # plt.scatter(extr_pts[:,0], extr_pts[:,1])
                # plt.show()
                if self.is_val == True:
                    extr_pts = extreme_points_fixed(msk, self.pert)
                elif self.is_val == False:
                    extr_pts = extreme_points(msk, self.pert)
                # extr_pts = sample['points']
                # try:
                h_map, d1, d2      = generate_mvL1L2_image_skewed_axes(msk, extreme_points=extr_pts, FULL_IMAGE_WEIGHTS=1, d2_THRESH=None, tau=self.tau)
                # except:
                    # plt.imshow(msk)
                    # print(extr_pts)
                    # plt.savefig('failure.png')
            elif self.hm_type == 'gaussian':
                h_map = generate_mvgauss_image(msk, FULL_IMAGE_WEIGHTS=1, tau = 0.5)
            hm = normalize_wtMap(h_map) * 255

        x,y,z = img.shape
        n_dims = z +1
        res = np.zeros((x,y,n_dims))
        res[..., :n_dims - 1] = img
        res[..., n_dims - 1] = hm
        sample['with_hm'] = res
        return sample



class ConcatInputs(object):

    def __init__(self, elems=('image', 'point')):
        self.elems = elems

    def __call__(self, sample):

        res = sample[self.elems[0]]

        for elem in self.elems[1:]:
            assert(sample[self.elems[0]].shape[:2] == sample[elem].shape[:2])

            # Check if third dimension is missing
            tmp = sample[elem]
            if tmp.ndim == 2:
                tmp = tmp[:, :, np.newaxis]

            res = np.concatenate((res, tmp), axis=2)

        sample['concat'] = res

        return sample

    def __str__(self):
        return 'ExtremePoints:'+str(self.elems)


class CropFromMaskStatic(object):
    """
    Returns image cropped in bounding box from a given mask
    """
    def __init__(self, crop_elems=('image', 'gt'),
                 mask_elem='gt',
                 relax=0,
                 zero_pad=False):

        self.crop_elems = crop_elems
        self.mask_elem = mask_elem
        self.relax = relax
        self.zero_pad = zero_pad

    def __call__(self, sample):
        _target = sample[self.mask_elem]
        if _target.ndim == 2:
            _target = np.expand_dims(_target, axis=-1)
        for elem in self.crop_elems:
            _img = sample[elem]
            _crop = []
            if self.mask_elem == elem:
                if _img.ndim == 2:
                    _img = np.expand_dims(_img, axis=-1)
                for k in range(0, _target.shape[-1]):
                    _tmp_img = _img[..., k]
                    _tmp_target = _target[..., k]
                    if np.max(_target[..., k]) == 0:
                        _crop.append(np.zeros(_tmp_img.shape, dtype=_img.dtype))
                    else:
                        _crop.append(helpers.crop_from_mask(_tmp_img, _tmp_target, relax=self.relax, zero_pad=self.zero_pad))
            else:
                for k in range(0, _target.shape[-1]):
                    if np.max(_target[..., k]) == 0:
                        _crop.append(np.zeros(_img.shape, dtype=_img.dtype))
                    else:
                        _tmp_target = _target[..., k]
                        _crop.append(helpers.crop_from_mask(_img, _tmp_target, relax=self.relax, zero_pad=self.zero_pad))
            if len(_crop) == 1:
                sample['crop_' + elem] = _crop[0]
            else:
                sample['crop_' + elem] = _crop
        return sample

    def __str__(self):
        return 'CropFromMask:(crop_elems='+str(self.crop_elems)+', mask_elem='+str(self.mask_elem)+\
               ', relax='+str(self.relax)+',zero_pad='+str(self.zero_pad)+')'

class CropFromMask(object):
    """
    Returns image cropped in bounding box from a given mask
    """
    def __init__(self, crop_elems=('image', 'gt'),
                 mask_elem='gt',
                 zero_pad=False, d = 512, is_val = None):

        self.crop_elems = crop_elems
        self.mask_elem = mask_elem
        self.zero_pad = zero_pad
        self.d = d
        self.is_val = is_val
        dz = int(np.sqrt(self.d**2 * 0.5))
        # Some objects are extremely small, we believe that it is always better to include some context. If the function is applied to these objects, 
        # it selects very small relaxation, leading to extreme zooming. That's why we set a lower threshold for zooming. We set it to ensure that zoomed
        # area must be at least 4 percent of the original image size.
        min_object_dim = self.d / 5
        self.thresh = ((self.d - dz)*min_object_dim) / (2*dz)
        if self.is_val == True:
            self.dz = dz
        elif self.is_val == False:
            self.min_ = int(np.sqrt(self.d**2 * 0.45))
            self.max_ = int(np.sqrt(self.d**2 * 0.6))

    def __call__(self, sample):
        if self.is_val == False:
            self.dz = np.array(np.random.randint(self.min_,self.max_)).astype(np.float32)
        _target = sample[self.mask_elem]
        if len(np.unique(_target)) == 1:
            sample['crop_image'] = sample['image']
            sample['crop_gt'] = sample['gt']
            return sample 
        if _target.ndim == 2:
            _target = np.expand_dims(_target, axis=-1)
        for elem in self.crop_elems:
            _img = sample[elem]
            _crop = []
            ### dynamic relax crop ###
            bbox = helpers.get_bbox(_target)
            d = np.maximum(bbox[2] - bbox[0], bbox[3] - bbox[1])
            if d < 1:
                print("Very small objects detected")
                print(sample['id'])
            zoom_factor = self.dz/d
            crop_relax = (self.d-d*zoom_factor)/(2*zoom_factor)
            crop_relax = np.maximum(crop_relax, self.thresh)
            self.crop_relax = np.ceil(crop_relax).astype(int)
            sample['crop_relax'] = self.crop_relax
            ###                    ###
            if self.mask_elem == elem:
                if _img.ndim == 2:
                    _img = np.expand_dims(_img, axis=-1)
                for k in range(0, _target.shape[-1]):
                    _tmp_img = _img[..., k]
                    _tmp_target = _target[..., k]
                    if np.max(_target[..., k]) == 0:
                        _crop.append(np.zeros(_tmp_img.shape, dtype=_img.dtype))
                    else:
                        _crop.append(helpers.crop_from_mask(_tmp_img, _tmp_target, relax=self.crop_relax, zero_pad=self.zero_pad))
            else:
                for k in range(0, _target.shape[-1]):
                    if np.max(_target[..., k]) == 0:
                        _crop.append(np.zeros(_img.shape, dtype=_img.dtype))
                    else:
                        _tmp_target = _target[..., k]
                        _crop.append(helpers.crop_from_mask(_img, _tmp_target, relax=self.crop_relax, zero_pad=self.zero_pad))
            if len(_crop) == 1:
                sample['crop_' + elem] = _crop[0]
            else:
                sample['crop_' + elem] = _crop
        return sample

    def __str__(self):
        return 'CropFromMask:(crop_elems='+str(self.crop_elems)+', mask_elem='+str(self.mask_elem)+\
               ', relax='+str('dynamic')+',zero_pad='+str(self.zero_pad)+')'

class ToImage(object):
    """
    Return the given elements between 0 and 255
    """
    def __init__(self, norm_elem='image', custom_max=255.):
        self.norm_elem = norm_elem
        self.custom_max = custom_max

    def __call__(self, sample):
        if isinstance(self.norm_elem, tuple):
            for elem in self.norm_elem:
                tmp = sample[elem]
                sample[elem] = self.custom_max * (tmp - tmp.min()) / (tmp.max() - tmp.min() + 1e-10)
        else:
            tmp = sample[self.norm_elem]
            sample[self.norm_elem] = self.custom_max * (tmp - tmp.min()) / (tmp.max() - tmp.min() + 1e-10)
        return sample

    def __str__(self):
        return 'NormalizeImage'


class ToTensor(object):
    """Convert ndarrays in sample to Tensors."""

    def __call__(self, sample):

        for elem in sample.keys():
            if 'id' in elem or 'meta' in elem or 'crop_relax' in elem:
                continue
            elif 'bbox' in elem:
                tmp = sample[elem]
                sample[elem] = torch.from_numpy(tmp)
                continue

            tmp = sample[elem]

            if tmp.ndim == 2:
                tmp = tmp[:, :, np.newaxis]

            # swap color axis because
            # numpy image: H x W x C
            # torch image: C X H X W
            tmp = tmp.transpose((2, 0, 1))
            sample[elem] = torch.from_numpy(tmp).type(torch.FloatTensor)

        return sample

    def __str__(self):
        return 'ToTensor'
