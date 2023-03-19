#! /usr/bin/env python
"""Module with the HCI<post-processing algorithms> classes."""

__author__ = "Carlos Alberto Gomez Gonzalez, Ralf Farkas"
__all__ = [
    "PPFrameDiff",
    "PPMedianSub",
    "PPPcaFF",
    "PPPcaAnn",
    "PPLoci",
    "PPLLSG",
    "PPNMF",
    "PPAndromeda",
    "PPFMMF",
]

import pickle
import numpy as np
from sklearn.base import BaseEstimator

from .dataset import Dataset
from .metrics import snrmap
from .invprob import andromeda, fmmf
from .psfsub import (
    pca,
    llsg,
    median_sub,
    xloci,
    pca_annular,
    frame_diff,
    nmf,
    nmf_annular,
)
from .config.utils_conf import algo_calculates_decorator as calculates

# TODO : cross-check every algorithm validity

PROBLEMATIC_ATTRIBUTE_NAMES = ["_repr_html_"]


class PostProc(BaseEstimator):
    """Base post-processing algorithm class."""

    def __init__(self, locals_dict, *skip):
        """
        Set up the algorithm parameters.

        This does multiple things:

        - verify that ``dataset`` is a Dataset object or ``None`` (it could
          also be provided to ``run``)
        - store all the keywords (from ``locals_dict``) as object attributes, so
          they can be accessed e.g. in the ``run()`` method
        - print out the full algorithm settings (user provided parameters +
          default ones) if ``verbose=True``

        Parameters
        ----------
        locals_dict : dict
            This should be ``locals()``. ``locals()`` contains *all* the
            variables defined in the local scope. Passed to
            ``self._store_args``.
        *skip : list of strings
            Passed on to ``self._store_args``. Refer to its documentation.

        Examples
        --------
        .. code:: python

            # when subclassing PostProc, make sure you call super()
            # with locals()! This means:

            class MySuperAlgo(PostProc):
                def __init__(self, algo_param_1=42, cool=True):
                    super(MySuperAlgo, self).__init__(locals())

                @calculates("frame")
                def run(self, dataset=None):
                    self.frame = 2 * self.algo_param_1

        """
        dataset = locals_dict.get("dataset", None)
        if not isinstance(dataset, (Dataset, type(None))):
            raise ValueError("`dataset` must be a Dataset object or None")

        self._store_args(locals_dict, *skip)

        verbose = locals_dict.get("verbose", True)
        if verbose:
            self._print_parameters()

    def _print_parameters(self):
        """Print out the parameters of the algorithm."""
        dicpar = self.get_params()
        for key in dicpar.keys():
            print("{}: {}".format(key, dicpar[key]))

    def _store_args(self, locals_dict, *skip):
        # TODO: this could be integrated with sklearn's BaseEstimator methods
        for k in locals_dict:
            if k == "self" or k in skip:
                continue
            setattr(self, k, locals_dict[k])

    def _get_dataset(self, dataset=None, verbose=True):
        """
        Handle a dataset passed to ``run()``.

        It is possible to specify a dataset using the constructor, or using the
        ``run()`` function. This helper function checks that there is a dataset
        to work with.

        Parameters
        ----------
        dataset : Dataset or None, optional
        verbose : bool, optional
            If ``True``, a message is printed out when a previous dataset was
            overwritten.

        Returns
        -------
        dataset : Dataset

        """
        if dataset is None:
            dataset = self.dataset
            if self.dataset is None:
                raise ValueError("no dataset specified!")
        else:
            if self.dataset is not None and verbose:
                print(
                    "a new dataset was provided to run(), all previous "
                    "results were cleared."
                )
            self.dataset = dataset
            self._reset_results()

        return dataset

    # TODO : identify the problem around the element `_repr_html_`
    def _get_calculations(self):
        """
        Get a list of all attributes which are *calculated*.

        This iterates over all the elements in an object and finds the functions
        which were decorated with ``@calculates`` (which are identified by the
        function attribute ``_calculates``). It then stores the calculated
        attributes, together with the corresponding method, and returns it.

        Returns
        -------
        calculations : dict
            Dictionary mapping a single "calculated attribute" to the method
            which calculates it.

        """
        calculations = {}
        for e in dir(self):
            # BLACKMAGIC : _repr_html_ must be skipped
            """
            `_repr_html_` is an element of the directory of the PostProc object which
            causes the search of calculated attributes to overflow, looping indefinitely
            and never reaching the actual elements containing those said attributes.
            It will be skipped until the issue has been properly identified and fixed.
            You can uncomment the block below to observe how the directory loops after
            reaching that element - acknowledging you are not skipping it.
            """
            if e not in PROBLEMATIC_ATTRIBUTE_NAMES:
                try:
                    # print(
                    #     "directory element : ",
                    #     e,
                    #     ", calculations list : ",
                    #     calculations,
                    # )
                    for k in getattr(getattr(self, e), "_calculates"):
                        calculations[k] = e
                except AttributeError:
                    pass

        return calculations

    def _reset_results(self):
        """
        Remove all calculated results from the object.

        By design, the PostProc's can be initialized without a dataset,
        so the dataset can be provided to the ``run`` method. This makes it
        possible to run the same algorithm on multiple datasets. In order not to
        keep results from an older ``run`` call when working on a new dataset,
        the stored results are reset using this function every time the ``run``
        method is called.
        """
        for attr in self._get_calculations():
            try:
                delattr(self, attr)
            except AttributeError:
                pass  # attribute/result was not calculated yet. Skip.

    def __getattr__(self, a):
        """
        ``__getattr__`` is only called when an attribute does *not* exist.

        Catching this event allows us to output proper error messages when an
        attribute was not calculated yet.
        """
        calculations = self._get_calculations()
        if a in calculations:
            raise AttributeError(
                "The '{}' was not calculated yet. Call '{}' "
                "first.".format(a, calculations[a])
            )
        else:
            # this raises a regular AttributeError:
            return self.__getattribute__(a)

    def _show_attribute_help(self, function_name):
        """
        Print information about the attributes a method calculated.

        This is called *automatically* when a method is decorated with
        ``@calculates``.

        Parameters
        ----------
        function_name : string
            The name of the method.

        """
        calculations = self._get_calculations()

        print("These attributes were just calculated:")
        for a, f in calculations.items():
            if hasattr(self, a) and function_name == f:
                print("\t{}".format(a))

        not_calculated_yet = [
            (a, f)
            for a, f in calculations.items()
            if (f not in self._called_calculators and not hasattr(self, a))
        ]
        if len(not_calculated_yet) > 0:
            print("The following attributes can be calculated now:")
            for a, f in not_calculated_yet:
                print("\t{}\twith .{}()".format(a, f))

    @calculates("snr_map", "detection_map")
    def make_snrmap(
        self,
        approximated=False,
        plot=False,
        known_sources=None,
        nproc=None,
        verbose=False,
    ):
        """
        Calculate a S/N map from ``self.frame_final``.

        Parameters
        ----------
        approximated : bool, optional
            If True, a proxy to the S/N calculation will be used. If False, the
            Mawet et al. 2014 definition is used.
        plot : bool, optional
            If True plots the S/N map. True by default.
        known_sources : None, tuple or tuple of tuples, optional
            To take into account existing sources. It should be a tuple of
            float/int or a tuple of tuples (of float/int) with the coordinate(s)
            of the known sources.
        nproc : int or None
            Number of processes for parallel computing.
        verbose: bool, optional
            Whether to print timing or not.

        Note
        ----
        This is needed for "classic" algorithms that produce a final residual
        image in their ``.run()`` method. To obtain a "detection map", which can
        be used for counting true/false positives, a SNR map has to be created.
        For other algorithms (like ANDROMEDA) which directly create a SNR or a
        probability map, this method should be overwritten and thus disabled.

        """
        if self.dataset.cube.ndim == 4:
            fwhm = np.mean(self.dataset.fwhm)
        else:
            fwhm = self.dataset.fwhm

        self.snr_map = snrmap(
            self.frame_final,
            fwhm,
            approximated,
            plot=plot,
            known_sources=known_sources,
            nproc=nproc,
            verbose=verbose,
        )

        self.detection_map = self.snr_map

    def save(self, filename):
        """
        Pickle the algo object and save it to disk.

        Note that this also saves the associated ``self.dataset``, in a
        non-optimal way.
        """
        pickle.dump(self, open(filename, "wb"))

    @calculates("frame_final")
    def run(self, dataset=None, nproc=1, verbose=True):
        """
        Run the algorithm. Should at least set `` self.frame_final``.

        Note
        ----
        This is the required signature of the ``run`` call. Child classes can
        add their own keyword arguments if needed.
        """
        raise NotImplementedError


class PPFrameDiff(PostProc):
    """Post-processing frame differencing algorithm."""

    def __init__(
        self,
        dataset=None,
        metric="manhattan",
        dist_threshold=50,
        n_similar=None,
        delta_rot=0.5,
        radius_int=2,
        asize=4,
        ncomp=None,
        imlib="vip-fft",
        interpolation="lanczos4",
        collapse="median",
        nproc=1,
        verbose=True,
    ):
        """
        Set up the frame differencing algorithm parameters.

        Parameters
        ----------
        dataset : Dataset object
            A Dataset object to be processed.
        metric : str, optional
            Distance metric to be used ('cityblock', 'cosine', 'euclidean', 'l1',
            'l2', 'manhattan', 'correlation', etc). It uses the scikit-learn
            function ``sklearn.metrics.pairwise.pairwise_distances`` (check its
            documentation).
        dist_threshold : int
            Indices with a distance larger than ``dist_threshold`` percentile will
            initially discarded.
        n_similar : None or int, optional
            If a postive integer value is given, then a median combination of
            ``n_similar`` frames will be used instead of the most similar one.
        delta_rot : int
            Minimum parallactic angle distance between the pairs.
        radius_int : int, optional
            The radius of the innermost annulus. By default is 0, if >0 then the
            central circular area is discarded.
        asize : int, optional
            The size of the annuli, in pixels.
        ncomp : None or int, optional
            If a positive integer value is given, then the annulus-wise PCA low-rank
            approximation with ``ncomp`` principal components will be subtracted.
            The pairwise subtraction will be performed on these residuals.
        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to cpu_count()/2. By default the algorithm works
            in single-process mode.
        imlib : str, opt
            See description in vip.preproc.frame_rotate()
        interpolation : str, opt
            See description in vip.preproc.frame_rotate()
        collapse: str, opt
            What to do with derotated residual cube? See options of
            vip.preproc.cube_collapse()
        verbose : bool, optional
            If True prints to stdout intermediate info.

        """
        super(PPFrameDiff, self).__init__(locals())

    @calculates("frame_final")
    def run(self, dataset=None, nproc=1, full_output=True, verbose=True, **rot_options):
        """
        Run the post-processing median subtraction algorithm for model PSF subtraction.

        Parameters
        ----------
        dataset : Dataset object
            A Dataset object to be processed.
        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to cpu_count()/2. By default the algorithm works
            in single-process mode.
        full_output: bool, optional
            Whether to return the final median combined image only or with other
            intermediate arrays.
        verbose : bool, optional
            If True prints to stdout intermediate info.
        rot_options: dictionary, optional
            Dictionary with optional keyword values for "border_mode", "mask_val",
            "edge_blend", "interp_zeros", "ker" (see documentation of
            ``vip_hci.preproc.frame_rotate``).

        """
        dataset = self._get_dataset(dataset, verbose)

        if dataset.fwhm is None:
            raise ValueError("`fwhm` has not been set")

        res = frame_diff(
            cube=dataset.cube,
            angle_list=dataset.angles,
            fwhm=dataset.fwhm,
            metric=self.metric,
            dist_threshold=self.dist_threshold,
            n_similar=self.n_similar,
            delta_rot=self.delta_rot,
            radius_int=self.radius_int,
            asize=self.asize,
            ncomp=self.ncomp,
            imlib=self.imlib,
            interpolation=self.interpolation,
            collapse=self.collapse,
            nproc=nproc,
            full_output=True,
            verbose=verbose,
            **rot_options
        )

        self.frame_final = res


class PPMedianSub(PostProc):
    """Post-processing median subtraction algorithm."""

    def __init__(
        self,
        flux_sc_list=None,
        dataset=None,
        radius_int=0,
        asize=4,
        delta_rot=1,
        delta_sep=(0.1, 1),
        mode="fullfr",
        nframes=4,
        sdi_only=False,
        imlib="vip-fft",
        interpolation="lanczos4",
        collapse="median",
        verbose=True,
    ):
        """
        Set up the median sub algorithm parameters.

        Parameters
        ----------
        dataset : Dataset object
            A Dataset object to be processed.
        flux_sc_list : numpy ndarray, 1d
            In the case of IFS data (ADI+SDI), this is the list of flux scaling
            factors applied to each spectral frame after geometrical rescaling.
            These should be set to either the ratio of stellar fluxes between the
            last spectral channel and the other channels, or to the second output
            of `preproc.find_scal_vector` (when using 2 free parameters). If not
            provided, the algorithm will still work, but with a lower efficiency
            at subtracting the stellar halo.
        radius_int : int, optional
            The radius of the innermost annulus. By default is 0, if >0 then the
            central circular area is discarded.
        asize : int, optional
            The size of the annuli, in pixels.
        delta_rot : int, optional
            Factor for increasing the parallactic angle threshold, expressed in
            FWHM. Default is 1 (excludes 1 FHWM on each side of the considered
            frame).
        delta_sep : float or tuple of floats, optional
            The threshold separation in terms of the mean FWHM (for ADI+mSDI data).
            If a tuple of two values is provided, they are used as the lower and
            upper intervals for the threshold (grows as a function of the
            separation).
        mode : {'fullfr', 'annular'}, str optional
            In ``fullfr`` mode only the median frame is subtracted, in ``annular``
            mode also the 4 closest frames given a PA threshold (annulus-wise) are
            subtracted.
        nframes : int or None, optional
            Number of frames (even value) to be used for building the optimized
            reference PSF when working in ``annular`` mode. None by default, which
            means that all frames, excluding the thresholded ones, are used.
        sdi_only: bool, optional
            In the case of IFS data (ADI+SDI), whether to perform median-SDI, or
            median-ASDI (default).
        imlib : str, optional
            See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        interpolation : str, optional
            See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        collapse : {'median', 'mean', 'sum', 'trimmean'}, str optional
            Sets the way of collapsing the frames for producing a final image.
        verbose : bool, optional
            If True prints to stdout intermediate info.

        """
        super(PPMedianSub, self).__init__(locals())

    @calculates("cube_residuals", "cube_residuals_der", "frame_final")
    def run(self, dataset=None, nproc=1, full_output=True, verbose=True, **rot_options):
        """
        Run the post-processing median subtraction algorithm for model PSF subtraction.

        Parameters
        ----------
        dataset : Dataset object
            An Dataset object to be processed.
        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to cpu_count()/2. By default the algorithm works
            in single-process mode.
        full_output: bool, optional
            Whether to return the final median combined image only or with other
            intermediate arrays.
        verbose : bool, optional
            If True prints to stdout intermediate info.
        rot_options: dictionary, optional
            Dictionary with optional keyword values for "border_mode", "mask_val",
            "edge_blend", "interp_zeros", "ker" (see documentation of
            ``vip_hci.preproc.frame_rotate``).

        """
        dataset = self._get_dataset(dataset, verbose)

        if self.mode == "annular" and dataset.fwhm is None:
            raise ValueError("`fwhm` has not been set")

        res = median_sub(
            cube=dataset.cube,
            angle_list=dataset.angles,
            scale_list=dataset.wavelengths,
            flux_sc_list=self.flux_sc_list,
            fwhm=dataset.fwhm,
            radius_int=self.radius_int,
            asize=self.asize,
            delta_rot=self.delta_rot,
            delta_sep=self.delta_sep,
            mode=self.mode,
            nframes=self.nframes,
            sdi_only=self.sdi_only,
            imlib=self.imlib,
            interpolation=self.interpolation,
            collapse=self.collapse,
            nproc=nproc,
            full_output=True,
            verbose=verbose,
            **rot_options
        )

        self.cube_residuals, self.cube_residuals_der, self.frame_final = res


class PPPcaFF(PostProc):
    """Post-processing full-frame PCA algorithm."""

    def __init__(
        self,
        dataset=None,
        ncomp=1,
        svd_mode="lapack",
        scaling=None,
        mask_center_px=None,
        source_xy=None,
        delta_rot=1,
        adimsdi="double",
        crop_ifs=True,
        imlib="vip-fft",
        imlib2="vip-fft",
        interpolation="lanczos4",
        collapse="median",
        collapse_ifs="mean",
        ifs_collapse_range="all",
        mask_rdi=None,
        check_mem=True,
        batch=None,
        weights=None,
        conv=False,
        cube_sig=None,
    ):
        """Set up the full-frame PCA algorithm parameters.

        Parameters
        ----------
        dataset : Dataset object, optional
            An Dataset object to be processed. Can also be passed to ``.run()``.
        ncomp : int, float or tuple of int/None, or list, optional
            How many PCs are used as a lower-dimensional subspace to project the
            target frames (see documentation of ``vip_hci.psfsub.pca_fullfr`` for
            information on the various modes).
        svd_mode : {'lapack', 'arpack', 'eigen', 'randsvd', 'cupy', 'eigencupy',
            'randcupy', 'pytorch', 'eigenpytorch', 'randpytorch'}, str optional
            Switch for the SVD method/library to be used.

            * ``lapack``: uses the LAPACK linear algebra library through Numpy
              and it is the most conventional way of computing the SVD
              (deterministic result computed on CPU).

            * ``arpack``: uses the ARPACK Fortran libraries accessible through
              Scipy (computation on CPU).

            * ``eigen``: computes the singular vectors through the
              eigendecomposition of the covariance M.M' (computation on CPU).

            * ``randsvd``: uses the randomized_svd algorithm implemented in
              Sklearn (computation on CPU), proposed in [HAL09]_.

            * ``cupy``: uses the Cupy library for GPU computation of the SVD as in
              the LAPACK version. `

            * ``eigencupy``: offers the same method as with the ``eigen`` option
              but on GPU (through Cupy).

            * ``randcupy``: is an adaptation of the randomized_svd algorithm,
              where all the computations are done on a GPU (through Cupy). `

            * ``pytorch``: uses the Pytorch library for GPU computation of the SVD.

            * ``eigenpytorch``: offers the same method as with the ``eigen``
              option but on GPU (through Pytorch).

            * ``randpytorch``: is an adaptation of the randomized_svd algorithm,
              where all the linear algebra computations are done on a GPU
              (through Pytorch).
        scaling : {None, "temp-mean", spat-mean", "temp-standard",
            "spat-standard"}, None or str optional
            Pixel-wise scaling mode using ``sklearn.preprocessing.scale`` function.
            If set to None, the input matrix is left untouched. Otherwise:

            * ``temp-mean``: temporal px-wise mean is subtracted.

            * ``spat-mean``: spatial mean is subtracted.

            * ``temp-standard``: temporal mean centering plus scaling pixel values
              to unit variance. HIGHLY RECOMMENDED FOR ASDI AND RDI CASES!

            * ``spat-standard``: spatial mean centering plus scaling pixel values
              to unit variance.
        mask_center_px : None or int
            If None, no masking is done. If an integer > 1 then this value is the
            radius of the circular mask.
        source_xy : tuple of int, optional
            For ADI-PCA, this triggers a frame rejection in the PCA library, with
            ``source_xy`` as the coordinates X,Y of the center of the annulus where
            the PA criterion is estimated. When ``ncomp`` is a tuple, a PCA grid is
            computed and the S/Ns (mean value in a 1xFWHM circular aperture) of the
            given (X,Y) coordinates are computed.
        delta_rot : int, optional
            Factor for tuning the parallactic angle threshold, expressed in FWHM.
            Default is 1 (excludes 1xFHWM on each side of the considered frame).
        adimsdi : {'single', 'double'}, str optional
            Changes the way the 4d cubes (ADI+mSDI) are processed. Basically it
            determines whether a single or double pass PCA is going to be computed.

            * ``single``: the multi-spectral frames are rescaled wrt the largest
              wavelength to align the speckles and all the frames (n_channels *
              n_adiframes) are processed with a single PCA low-rank approximation.

            * ``double``: a first stage is run on the rescaled spectral frames, and
              a second PCA frame is run on the residuals in an ADI fashion.

        crop_ifs: bool, optional
            [adimsdi='single'] If True cube is cropped at the moment of frame
            rescaling in wavelength. This is recommended for large FOVs such as the
            one of SPHERE, but can remove significant amount of information close
            to the edge of small FOVs (e.g. SINFONI).
        imlib : str, optional
            See the documentation of ``vip_hci.preproc.frame_rotate``.
        imlib2 : str, optional
            See the documentation of ``vip_hci.preproc.cube_rescaling_wavelengths``.
        interpolation : str, optional
            See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        collapse : {'median', 'mean', 'sum', 'trimmean'}, str optional
            Sets how temporal residual frames should be combined to produce an
            ADI image.
        collapse_ifs : {'median', 'mean', 'sum', 'trimmean'}, str optional
            Sets how spectral residual frames should be combined to produce an
            mSDI image.
        ifs_collapse_range: str 'all' or tuple of 2 int
            If a tuple, it should contain the first and last channels where the mSDI
            residual channels will be collapsed (by default collapses all channels).
        mask_rdi: 2d numpy array, opt
            If provided, this binary mask will be used either in RDI mode or in
            ADI+mSDI (2 steps) mode. The projection coefficients for the principal
            components will be found considering the area covered by the mask
            (useful to avoid self-subtraction in presence of bright disc signal)
        check_memory : bool, optional
            If True, it checks that the input cube is smaller than the available
            system memory.
        batch : None, int or float, optional
            When it is not None, it triggers the incremental PCA (for ADI and
            ADI+mSDI cubes). If an int is given, it corresponds to the number of
            frames in each sequential mini-batch. If a float (0, 1] is given, it
            corresponds to the size of the batch is computed wrt the available
            memory in the system.
        weights: 1d numpy array or list, optional
            Weights to be applied for a weighted mean. Need to be provided if
            collapse mode is 'wmean'.
        cube_sig: numpy ndarray, opt
            Cube with estimate of significant authentic signals. If provided, this
            will subtracted before projecting cube onto reference cube.
        """
        super(PPPcaFF, self).__init__(locals())

    @calculates(
        "frame_final",
        "cube_reconstructed",
        "cube_residuals",
        "cube_residuals_der",
        "pcs",
        "cube_residuals_per_channel",
        "cube_residuals_per_channel_der",
        "cube_residuals_resc",
    )
    def run(self, dataset=None, nproc=1, verbose=True, full_output=True, **rot_options):
        """
        Run the post-processing PCA algorithm for model PSF subtraction.

        Note
        ----
        creates/sets the ``self.frame_final`` attribute, and depending on the
        input parameters:

            3D case:
                cube_reconstructed
                cube_residuals
                cube_residuals_der
            3D case, source_xy is None:
                cube_residuals
                pcs
            4D case, adimsdi="double":
                cube_residuals_per_channel
                cube_residuals_per_channel_der
            4D case, adimsdi="single":
                cube_residuals
                cube_residuals_resc

        Parameters
        ----------
        dataset : Dataset, optional
            Dataset to process. If not provided, ``self.dataset`` is used (as
            set when initializing this object).
        nproc : int, optional
        verbose : bool, optional
            If True prints to stdout intermediate info.
        full_output: boolean, optional
            Whether to return the final median combined image only or with
            other intermediate arrays.
        rot_options: dictionary, optional
            Dictionary with optional keyword values for "border_mode", "mask_val",
            "edge_blend", "interp_zeros", "ker" (see documentation of
            ``vip_hci.preproc.frame_rotate``)

        """
        dataset = self._get_dataset(dataset, verbose)

        if self.source_xy is not None and dataset.fwhm is None:
            raise ValueError("`fwhm` has not been set")

        # TODO : review the wavelengths attribute to be a scale_list instead

        # TODO : fuse PPPca and PPPcaAnn into one object

        res = pca(
            cube=dataset.cube,
            angle_list=dataset.angles,
            cube_ref=dataset.cuberef,
            scale_list=dataset.wavelengths,
            ncomp=self.ncomp,
            svd_mode=self.svd_mode,
            scaling=self.scaling,
            mask_center_px=self.mask_center_px,
            source_xy=self.source_xy,
            delta_rot=self.delta_rot,
            fwhm=dataset.fwhm,
            adimsdi=self.adimsdi,
            crop_ifs=self.crop_ifs,
            imlib=self.imlib,
            imlib2=self.imlib2,
            interpolation=self.interpolation,
            collapse=self.collapse,
            collapse_ifs=self.collapse_ifs,
            ifs_collapse_range=self.ifs_collapse_range,
            mask_rdi=self.mask_rdi,
            check_memory=self.check_mem,
            batch=self.batch,
            nproc=nproc,
            full_output=full_output,
            verbose=verbose,
            weights=self.weights,
            conv=self.conv,
            cube_sig=self.cube_sig,
            **rot_options
        )

        if dataset.cube.ndim == 3:
            if self.source_xy is not None:
                frame, recon_cube, res_cube, res_cube_der = res
                self.cube_reconstructed = recon_cube
                self.cube_residuals = res_cube
                self.cube_residuals_der = res_cube_der
                self.frame_final = frame
            else:
                frame, pcs, recon_cube, res_cube, res_cube_der = res
                self.pcs = pcs
                self.cube_reconstructed = recon_cube
                self.cube_residuals = res_cube
                self.cube_residuals_der = res_cube_der
                self.frame_final = frame
        elif dataset.cube.ndim == 4:
            if self.adimsdi == "double":
                frame, res_cube_chan, res_cube_chan_der = res
                self.cube_residuals_per_channel = res_cube_chan
                self.cube_residuals_per_channel_der = res_cube_chan_der
                self.frame_final = frame
            elif self.adimsdi == "single":
                frame, cube_allfr_res, cube_adi_res = res
                self.cube_residuals = cube_allfr_res
                self.cube_residuals_resc = cube_adi_res
                self.frame_final = frame


class PPPcaAnn(PostProc):
    """Post-processing local PCA algorithm."""

    def __init__(
        self,
        dataset=None,
        radius_int=0,
        asize=4,
        n_segments=1,
        delta_rot=(0.1, 1),
        delta_sep=(0.1, 1),
        ncomp=1,
        svd_mode="lapack",
        nproc=1,
        min_frames_lib=2,
        max_frames_lib=200,
        tol=1e-1,
        scaling=None,
        imlib="vip-fft",
        interpolation="lanczos4",
        collapse="median",
        collapse_ifs="mean",
        ifs_collapse_range="all",
        theta_init=0,
        weights=None,
        cube_sig=None,
    ):
        """Set up the local/smart PCA algorithm parameters.

        Parameters
        ----------
        dataset : Dataset object, optional
            An Dataset object to be processed. Can also be passed to ``.run()``.
        radius_int : int, optional
            The radius of the innermost annulus. By default is 0, if >0 then the
            central circular region is discarded.
        asize : float, optional
            The size of the annuli, in pixels.
        n_segments : int or list of ints or 'auto', optional
            The number of segments for each annulus. When a single integer is given
            it is used for all annuli. When set to 'auto', the number of segments is
            automatically determined for every annulus, based on the annulus width.
        delta_rot : float or tuple of floats, optional
            Factor for adjusting the parallactic angle threshold, expressed in
            FWHM. Default is 1 (excludes 1 FHWM on each side of the considered
            frame). If a tuple of two floats is provided, they are used as the lower
            and upper intervals for the threshold (grows linearly as a function of
            the separation).
        delta_sep : float or tuple of floats, optional
            The threshold separation in terms of the mean FWHM (for ADI+mSDI data).
            If a tuple of two values is provided, they are used as the lower and
            upper intervals for the threshold (grows as a function of the
            separation).
        ncomp : 'auto', int, tuple, 1d numpy array or tuple, optional
            How many PCs are used as a lower-dimensional subspace to project the
            target (sectors of) frames. Depends on the dimensionality of `cube`.

            * ADI and ADI+RDI (``cube`` is a 3d array): if a single integer is
              provided, then the same number of PCs will be subtracted at each
              separation (annulus). If a tuple is provided, then a different number
              of PCs will be used for each annulus (starting with the innermost
              one). If ``ncomp`` is set to ``auto`` then the number of PCs are
              calculated for each region/patch automatically.

            * ADI or ADI+RDI (``cube`` is a 4d array): same input format allowed as
              above. If ncomp is a list with the same length as the number of
              channels, each element of the list will be used as ``ncomp`` value
              (whether int, float or tuple) for each spectral channel.

            * ADI+mSDI case: ``ncomp`` must be a tuple (two integers) with the
              number of PCs obtained from each multi-spectral frame (for each
              sector) and the number of PCs used in the second PCA stage (ADI
              fashion, using the residuals of the first stage). If None then the
              second PCA stage is skipped and the residuals are de-rotated and
              combined.

        svd_mode : {'lapack', 'arpack', 'eigen', 'randsvd', 'cupy', 'eigencupy',
            'randcupy', 'pytorch', 'eigenpytorch', 'randpytorch'}, str optional
            Switch for the SVD method/library to be used.

            * ``lapack``: uses the LAPACK linear algebra library through Numpy
              and it is the most conventional way of computing the SVD
              (deterministic result computed on CPU).

            * ``arpack``: uses the ARPACK Fortran libraries accessible through
              Scipy (computation on CPU).

            * ``eigen``: computes the singular vectors through the
              eigendecomposition of the covariance M.M' (computation on CPU).

            * ``randsvd``: uses the randomized_svd algorithm implemented in
              Sklearn (computation on CPU), proposed in [HAL09]_.

            * ``cupy``: uses the Cupy library for GPU computation of the SVD as in
              the LAPACK version. `

            * ``eigencupy``: offers the same method as with the ``eigen`` option
              but on GPU (through Cupy).

            * ``randcupy``: is an adaptation of the randomized_svd algorithm,
              where all the computations are done on a GPU (through Cupy). `

            * ``pytorch``: uses the Pytorch library for GPU computation of the SVD.

            * ``eigenpytorch``: offers the same method as with the ``eigen``
              option but on GPU (through Pytorch).

            * ``randpytorch``: is an adaptation of the randomized_svd algorithm,
              where all the linear algebra computations are done on a GPU
              (through Pytorch).

        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to (cpu_count()/2).
        min_frames_lib : int, optional
            Minimum number of frames in the PCA reference library.
        max_frames_lib : int, optional
            Maximum number of frames in the PCA reference library. The more
            distant/decorrelated frames are removed from the library.
        tol : float, optional
            Stopping criterion for choosing the number of PCs when ``ncomp``
            is None. Lower values will lead to smaller residuals and more PCs.
        scaling : {None, "temp-mean", spat-mean", "temp-standard",
            "spat-standard"}, None or str optional
            Pixel-wise scaling mode using ``sklearn.preprocessing.scale``
            function. If set to None, the input matrix is left untouched. Otherwise:

            * ``temp-mean``: temporal px-wise mean is subtracted.

            * ``spat-mean``: spatial mean is subtracted.

            * ``temp-standard``: temporal mean centering plus scaling pixel values
              to unit variance. HIGHLY RECOMMENDED FOR ASDI AND RDI CASES!

            * ``spat-standard``: spatial mean centering plus scaling pixel values
              to unit variance.

        imlib : str, optional
            See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        interpolation : str, optional
            See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        collapse : {'median', 'mean', 'sum', 'trimmean'}, str optional
            Sets the way of collapsing the frames for producing a final image.
        collapse_ifs : {'median', 'mean', 'sum', 'trimmean', 'absmean'}, str opt
            Sets how spectral residual frames should be combined to produce an
            mSDI image.
        ifs_collapse_range: str 'all' or tuple of 2 int
            If a tuple, it should contain the first and last channels where the mSDI
            residual channels will be collapsed (by default collapses all channels).
        theta_init : int
            Initial azimuth [degrees] of the first segment, counting from the
            positive x-axis counterclockwise (irrelevant if n_segments=1).
        weights: 1d numpy array or list, optional
            Weights to be applied for a weighted mean. Need to be provided if
            collapse mode is 'wmean'.
        cube_sig: numpy ndarray, opt
            Cube with estimate of significant authentic signals. If provided, this
            will be subtracted before projecting cube onto reference cube.
        """
        super(PPPcaAnn, self).__init__(locals())

    @calculates("frame_final", "cube_residuals", "cube_residuals_der")
    def run(self, dataset=None, nproc=1, verbose=True, full_output=True, **rot_options):
        """
        Run the post-processing PCA algorithm for model PSF subtraction.

        Parameters
        ----------
        dataset : Dataset, optional
            Dataset to process. If not provided, ``self.dataset`` is used (as
            set when initializing this object).
        nproc : int, optional
        verbose : bool, optional
            If True prints to stdout intermediate info.
        full_output: boolean, optional
            Whether to return the final median combined image only or with
            other intermediate arrays.
        rot_options: dictionary, optional
            Dictionary with optional keyword values for "border_mode", "mask_val",
            "edge_blend", "interp_zeros", "ker" (see documentation of
            ``vip_hci.preproc.frame_rotate``)

        """
        dataset = self._get_dataset(dataset, verbose)

        if dataset.fwhm is None:
            raise ValueError("`fwhm` has not been set")

        if self.nproc is None:
            self.nproc = nproc

        # TODO : review the wavelengths attribute to be a scale_list instead

        res = pca_annular(
            cube=dataset.cube,
            angle_list=dataset.angles,
            cube_ref=dataset.cuberef,
            scale_list=dataset.wavelengths,
            radius_int=self.radius_int,
            fwhm=dataset.fwhm,
            asize=self.asize,
            n_segments=self.n_segments,
            delta_rot=self.delta_rot,
            delta_sep=self.delta_sep,
            ncomp=self.ncomp,
            svd_mode=self.svd_mode,
            nproc=self.nproc,
            min_frames_lib=self.min_frames_lib,
            max_frames_lib=self.max_frames_lib,
            tol=self.tol,
            scaling=self.scaling,
            imlib=self.imlib,
            interpolation=self.interpolation,
            collapse=self.collapse,
            collapse_ifs=self.collapse_ifs,
            ifs_collapse_range=self.ifs_collapse_range,
            theta_init=self.theta_init,
            weights=self.weights,
            cube_sig=self.cube_sig,
            full_output=full_output,
            verbose=verbose,
            **rot_options
        )

        self.cube_residuals, self.cube_residuals_der, self.frame_final = res


class PPLoci(PostProc):
    """Post-processing LOCI algorithm."""

    def __init__(
        self,
        dataset=None,
        metric="manhattan",
        dist_threshold=90,
        delta_rot=(0.1, 1),
        delta_sep=(0.1, 1),
        radius_int=0,
        asize=4,
        n_segments=4,
        solver="lstsq",
        tol=1e-2,
        optim_scale_fact=2,
        adimsdi="skipadi",
        imlib="vip-fft",
        interpolation="lanczos4",
        collapse="median",
    ):
        """
        Set up the LOCI algorithm parameters.

        Parameters
        ----------
        dataset : Dataset object, optional
            An Dataset object to be processed. Can also be passed to ``.run()``.
        metric : str, optional
            Distance metric to be used ('cityblock', 'cosine', 'euclidean', 'l1',
            'l2', 'manhattan', 'correlation', etc). It uses the scikit-learn
            function ``sklearn.metrics.pairwise.pairwise_distances`` (check its
            documentation).
        dist_threshold : int, optional
            Indices with a distance larger than ``dist_threshold`` percentile will
            initially discarded. 100 by default.
        delta_rot : float or tuple of floats, optional
            Factor for adjusting the parallactic angle threshold, expressed in
            FWHM. Default is 1 (excludes 1 FHWM on each side of the considered
            frame). If a tuple of two floats is provided, they are used as the lower
            and upper intervals for the threshold (grows linearly as a function of
            the separation).
        delta_sep : float or tuple of floats, optional
            The threshold separation in terms of the mean FWHM (for ADI+mSDI data).
            If a tuple of two values is provided, they are used as the lower and
            upper intervals for the threshold (grows as a function of the
            separation).
        radius_int : int, optional
            The radius of the innermost annulus. By default is 0, if >0 then the
            central circular region is discarded.
        asize : int, optional
            The size of the annuli, in pixels.
        n_segments : int or list of int or 'auto', optional
            The number of segments for each annulus. When a single integer is given
            it is used for all annuli. When set to 'auto', the number of segments is
            automatically determined for every annulus, based on the annulus width.
        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to cpu_count()/2. By default the algorithm works
            in single-process mode.
        solver : {'lstsq', 'nnls'}, str optional
            Choosing the solver of the least squares problem. ``lstsq`` uses the
            standard scipy least squares solver. ``nnls`` uses the scipy
            non-negative least-squares solver.
        tol : float, optional
            Valid when ``solver`` is set to lstsq. Sets the cutoff for 'small'
            singular values; used to determine effective rank of a. Singular values
            smaller than ``tol * largest_singular_value`` are considered zero.
            Smaller values of ``tol`` lead to smaller residuals (more aggressive
            subtraction).
        optim_scale_fact : float, optional
            If >1, the least-squares optimization is performed on a larger segment,
            similar to LOCI. The optimization segments share the same inner radius,
            mean angular position and angular width as their corresponding
            subtraction segments.
        adimsdi : {'skipadi', 'double'}, str optional
            Changes the way the 4d cubes (ADI+mSDI) are processed.

            ``skipadi``: the multi-spectral frames are rescaled wrt the largest
            wavelength to align the speckles and the least-squares model is
            subtracted on each spectral cube separately.

            ``double``: a first subtraction is done on the rescaled spectral frames
            (as in the ``skipadi`` case). Then the residuals are processed again in
            an ADI fashion.

        imlib : str, optional
            See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        interpolation : str, optional
            See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        collapse : {'median', 'mean', 'sum', 'trimmean'}, str optional
            Sets the way of collapsing the frames for producing a final image.

        """
        super(PPLoci, self).__init__(locals())

    @calculates("frame_final", "cube_res", "cube_der")
    def run(self, dataset=None, nproc=1, verbose=True, full_output=True):
        """
        Run the post-processing LOCI algorithm for model PSF subtraction.

        Parameters
        ----------
        dataset : Dataset, optional
            Dataset to process. If not provided, ``self.dataset`` is used (as
            set when initializing this object).
        nproc : int, optional
        verbose : bool, optional
            If True prints to stdout intermediate info.
        full_output: boolean, optional
            Whether to return the final median combined image only or with
            other intermediate arrays.
        rot_options: dictionary, optional
            Dictionary with optional keyword values for "border_mode", "mask_val",
            "edge_blend", "interp_zeros", "ker" (see documentation of
            ``vip_hci.preproc.frame_rotate``)

        """
        dataset = self._get_dataset(dataset, verbose)

        res = xloci(
            cube=dataset.cube,
            angle_list=dataset.angles,
            scale_list=dataset.wavelengths,
            fwhm=dataset.fwhm,
            metric=self.metric,
            dist_threshold=self.dist_threshold,
            delta_rot=self.delta_rot,
            delta_sep=self.delta_sep,
            radius_int=self.radius_int,
            asize=self.asize,
            n_segments=self.n_segments,
            nproc=nproc,
            solver=self.solver,
            tol=self.tol,
            optim_scale_fact=self.optim_scale_fact,
            admisdi=self.adimsdi,
            imlib=self.imlib,
            interpolation=self.interpolation,
            collapse=self.collapse,
            verbose=verbose,
            full_output=full_output,
        )

        self.cube_res, self.cube_der, self.frame_final = res


class PPLLSG(PostProc):
    """Post-processing LLSG algorithm."""

    def __init__(
        self,
        dataset=None,
        rank=10,
        thresh=1,
        max_iter=10,
        low_rank_ref=False,
        low_rank_mode="svd",
        auto_rank_mode="noise",
        residuals_tol=1e-1,
        cevr=0.9,
        thresh_mode="soft",
        nproc=1,
        asize=None,
        n_segments=4,
        azimuth_overlap=None,
        radius_int=None,
        random_seed=None,
        high_pass=None,
        collapse="median",
    ):
        """
        Set up the LLSG algorithm parameters.

        Parameters
        ----------
        rank : int, optional
            Expected rank of the L component.
        thresh : float, optional
            Factor that scales the thresholding step in the algorithm.
        max_iter : int, optional
            Sets the number of iterations.
        low_rank_ref :
            If True the first estimation of the L component is obtained from the
            remaining segments in the same annulus.
        low_rank_mode : {'svd', 'brp'}, optional
            Sets the method of solving the L update.
        auto_rank_mode : {'noise', 'cevr'}, str optional
            If ``rank`` is None, then ``auto_rank_mode`` sets the way that the
            ``rank`` is determined: the noise minimization or the cumulative
            explained variance ratio (when 'svd' is used).
        residuals_tol : float, optional
            The value of the noise decay to be used when ``rank`` is None and
            ``auto_rank_mode`` is set to ``noise``.
        cevr : float, optional
            Float value in the range [0,1] for selecting the cumulative explained
            variance ratio to choose the rank automatically (if ``rank`` is None).
        thresh_mode : {'soft', 'hard'}, optional
            Sets the type of thresholding.
        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to cpu_count()/2. By default the algorithm works
            in single-process mode.
        asize : int or None, optional
            If ``asize`` is None then each annulus will have a width of ``2*asize``.
            If an integer then it is the width in pixels of each annulus.
        n_segments : int or list of ints, optional
            The number of segments for each annulus. When a single integer is given
            it is used for all annuli.
        azimuth_overlap : int or None, optional
            Sets the amount of azimuthal averaging.
        radius_int : int, optional
            The radius of the innermost annulus. By default is 0, if >0 then the
            central circular area is discarded.
        random_seed : int or None, optional
            Controls the seed for the Pseudo Random Number generator.
        high_pass : odd int or None, optional
            If set to an odd integer <=7, a high-pass filter is applied to the
            frames. The ``vip_hci.var.frame_filter_highpass`` is applied twice,
            first with the mode ``median-subt`` and a large window, and then with
            ``laplacian-conv`` and a kernel size equal to ``high_pass``. 5 is an
            optimal value when ``fwhm`` is ~4.
        collapse : {'median', 'mean', 'sum', 'trimmean'}, str optional
            Sets the way of collapsing the frames for producing a final image.

        """
        super(PPLLSG, self).__init__(locals())

    @calculates("frame_final", "frame_l", "frame_s", "frame_g")
    def run(self, dataset=None, nproc=1, verbose=True, full_output=True, **rot_options):
        """
        Run the post-processing LLSG algorithm for model PSF subtraction.

        Parameters
        ----------
        dataset : Dataset, optional
            Dataset to process. If not provided, ``self.dataset`` is used (as
            set when initializing this object).
        nproc : int, optional
        verbose : bool, optional
            If True prints to stdout intermediate info.
        full_output: boolean, optional
            Whether to return the final median combined image only or with
            other intermediate arrays.
        rot_options: dictionary, optional
            Dictionary with optional keyword values for "border_mode", "mask_val",
            "edge_blend", "interp_zeros", "ker" (see documentation of
            ``vip_hci.preproc.frame_rotate``)

        """
        dataset = self._get_dataset(dataset, verbose)
        res = llsg(
            cube=dataset.cube,
            angle_list=dataset.angles,
            fwhm=dataset.fwhm,
            rank=self.rank,
            thresh=self.thresh,
            max_iter=self.max_iter,
            low_rank_ref=self.low_rank_ref,
            low_rank_mode=self.low_rank_mode,
            auto_rank_mode=self.auto_rank_mode,
            residuals_tol=self.residuals_tol,
            cevr=self.cevr,
            thresh_mode=self.thresh_mode,
            nproc=nproc,
            asize=self.asize,
            n_segments=self.n_segments,
            azimuth_overlap=self.azimuth_overlap,
            radius_int=self.radius_int,
            random_seed=self.random_seed,
            high_pass=self.high_pass,
            collapse=self.collapse,
            full_output=full_output,
            verbose=verbose,
            debug=False,
            **rot_options
        )

        self.list_l_array_der = res[0]
        self.list_s_array_der = res[1]
        self.list_g_array_der = res[2]

        self.frame_l = res[3]
        self.frame_s = res[4]
        self.frame_g = res[5]

        self.frame_final = self.frame_s


# TODO : update PPNMF doc to include 'nndsvdar' in init_svd section


class PPNMF(PostProc):
    """Post-processing full-frame non-negative matrix factorization algorithm."""

    def __init__(
        self,
        dataset=None,
        ncomp=1,
        scaling=None,
        max_iter=10000,
        random_state=None,
        mask_center_px=None,
        source_xy=None,
        delta_rot=[1, (0.1, 1)],
        fwhm=4,
        init_svd="nndsvd",
        collapse="median",
        full_output=False,
        verbose=True,
        cube_sig=None,
        handle_neg="mask",
        nmf_args={},
        radius_int=0,
        asize=4,
        n_segments=1,
        min_frames_lib=2,
        max_frames_lib=200,
        imlib="vip-fft",
        interpolation="lanczos4",
        theta_init=0,
        weights=None,
    ):
        """
        Set up the NMF algorithm parameters (full frame or annular).

        Parameters
        ----------
        dataset : Dataset object
            A Dataset object to be processed.
        ncomp : int, optional
            How many components are used as for low-rank approximation of the
            datacube.
        scaling : {None, 'temp-mean', 'spat-mean', 'temp-standard', 'spat-standard'}
            With None, no scaling is performed on the input data before SVD. With
            "temp-mean" then temporal px-wise mean subtraction is done, with
            "spat-mean" then the spatial mean is subtracted, with "temp-standard"
            temporal mean centering plus scaling to unit variance is done and with
            "spat-standard" spatial mean centering plus scaling to unit variance is
            performed.
        max_iter : int optional
            The number of iterations for the coordinate descent solver.
        random_state : int or None, optional
            Controls the seed for the Pseudo Random Number generator.
        mask_center_px : None or int
            If None, no masking is done. If an integer > 1 then this value is the
            radius of the circular mask.
        source_xy : tuple of int, optional
            For ADI-PCA, this triggers a frame rejection in the PCA library, with
            ``source_xy`` as the coordinates X,Y of the center of the annulus where
            the PA criterion is estimated. When ``ncomp`` is a tuple, a PCA grid is
            computed and the S/Ns (mean value in a 1xFWHM circular aperture) of the
            given (X,Y) coordinates are computed.
        delta_rot : array  (int and float/tuple of floats), optional
            Factor for tunning the parallactic angle threshold, expressed in FWHM.
            The int value is used for the full frame case, while the float goes for
            the annular case. Default is 1 (excludes 1xFHWM on each side of the
            considered frame). If a tuple of two floats is provided, they are used as
            the lower and upper intervals for the threshold (grows linearly as a
            function of the separation). !!! Important: this is used even if a reference
            cube is provided for RDI. This is to allow ARDI (PCA library built from both
            science and reference cubes). If you want to do pure RDI, set delta_rot
            to an arbitrarily high value such that the condition is never fulfilled
            for science frames to make it in the PCA library.
        fwhm : float, optional
            Known size of the FHWM in pixels to be used. Default value is 4.
        init_svd: str, optional {'nnsvd','nnsvda','random'}
            Method used to initialize the iterative procedure to find H and W.
            'nndsvd': non-negative double SVD recommended for sparseness
            'nndsvda': NNDSVD where zeros are filled with the average of cube;
            recommended when sparsity is not desired
            'random': random initial non-negative matrix
        collapse : {'median', 'mean', 'sum', 'trimmean'}, str optional
            Sets the way of collapsing the frames for producing a final image.
        full_output: boolean, optional
            Whether to return the final median combined image only or with other
            intermediate arrays.
        verbose : {True, False}, bool optional
            If True prints intermediate info and timing.
        handle_neg: str, opt {'subtr_min','mask','null'}
            Determines how to handle negative values: mask them, set them to zero,
            or subtract the minimum value in the arrays. Note: 'mask' or 'null'
            may leave significant artefacts after derotation of residual cube
            => those options should be used carefully (e.g. with proper treatment
            of masked values in non-derotated cube of residuals).
        nmf_args : dictionary, optional
            Additional arguments for scikit-learn NMF algorithm. See:
            https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.NMF.html

        """
        super(PPNMF, self).__init__(locals())

    @calculates(
        "nmf_reshaped",
        "cube_recon",
        "cube_residuals",
        "cube_residuals_der",
        "frame_final",
    )
    def run(
        self,
        runmode="fullframe",
        dataset=None,
        nproc=1,
        full_output=True,
        verbose=True,
        **rot_options
    ):
        """
        Run the post-processing NMF algorithm for model PSF subtraction.

        Parameters
        ----------
        runmode : {'fullframe', 'annular'}
            Defines which version of NMF to run between full frame and annular.
        dataset : Dataset object
            An Dataset object to be processed.
        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to cpu_count()/2.
        full_output: bool, optional
            Whether to return the final median combined image only or with other
            intermediate arrays.
        verbose : bool, optional
            If True prints to stdout intermediate info.
        rot_options: dictionary, optional
            Dictionary with optional keyword values for "border_mode", "mask_val",
            "edge_blend", "interp_zeros", "ker" (see documentation of
            ``vip_hci.preproc.frame_rotate``).

        """
        dataset = self._get_dataset(dataset, verbose)

        if dataset.fwhm is None:
            raise ValueError("`fwhm` has not been set")

        if runmode == "fullframe":
            res = nmf(
                cube=dataset.cube,
                angle_list=dataset.angles,
                cube_ref=dataset.cuberef,
                ncomp=self.ncomp,
                scaling=self.scaling,
                max_iter=self.max_iter,
                random_state=self.random_state,
                mask_center_px=self.mask_center_px,
                source_xy=self.source_xy,
                delta_rot=self.delta_rot[0],
                fwhm=dataset.fwhm,
                init_svd=self.init_svd,
                collapse=self.collapse,
                full_output=True,
                verbose=verbose,
                cube_sig=self.cube_sig,
                handle_neg=self.handle_neg,
                nmf_args=self.nmf_args,
                **rot_options
            )

            (
                self.nmf_reshaped,
                self.cube_recon,
                self.cube_residuals,
                self.cube_residuals_der,
                self.frame_final,
            ) = res
        else:
            res = nmf_annular(
                cube=dataset.cube,
                angle_list=dataset.angles,
                cube_ref=dataset.cuberef,
                radius_int=self.radius_int,
                fwhm=dataset.fwhm,
                asize=self.asize,
                n_segments=self.n_segments,
                delta_rot=self.delta_rot[1],
                ncomp=self.ncomp,
                init_svd=self.init_svd,
                nproc=nproc,
                min_frames_lib=self.min_frames_lib,
                max_frames_lib=self.max_frames_lib,
                scaling=self.scaling,
                imlib=self.imlib,
                interpolation=self.interpolation,
                collapse=self.collapse,
                full_output=True,
                verbose=verbose,
                theta_init=self.theta_init,
                weights=self.weights,
                cube_sig=self.cube_sig,
                handle_neg=self.handle_neg,
                max_iter=self.max_iter,
                random_state=self.random_state,
                nmf_args=self.nmf_args,
                **rot_options
            )

            (
                self.cube_residuals,
                self.cube_residuals_der,
                self.cube_recon,
                self.nmf_reshaped,
                self.frame_final,
            ) = res


class PPAndromeda(PostProc):
    """Post-processing ANDROMEDA algorithm."""

    def __init__(
        self,
        dataset=None,
        oversampling_fact=0.5,
        filtering_fraction=0.25,
        min_sep=0.5,
        annuli_width=1.0,
        roa=2.0,
        opt_method="lsq",
        nsmooth_snr=18,
        iwa=None,
        owa=None,
        precision=50,
        fast=False,
        homogeneous_variance=True,
        ditimg=1.0,
        ditpsf=None,
        tnd=1.0,
        total=False,
        multiply_gamma=True,
        verbose=True,
    ):
        r"""
        Set up the ANDROMEDA algorithm parameters.

        Parameters
        ----------
        dataset : Dataset object, optional
            An Dataset object to be processed. Can also be passed to ``.run()``.
        oversampling_fact : float
            Oversampling factor for the wavelength corresponding to the filter used
            to obtain ``cube`` (defined as the ratio between the wavelength of
            the filter and the Shannon wavelength). Usually above 1 and below 3.
            Note that in ANDROMEDA everything is coded in lambda/D unit so this is
            an important parameter. See Note for example calculation.
            IDL parameter: ``OVERSAMPLING_1_INPUT``
        filtering_fraction : float, optional
            Strength of the high-pass filter. If set to ``1``, no high-pass filter
            is used.
            IDL parameter: ``FILTERING_FRACTION_INPUT``
        min_sep : float, optional
            Angular separation is assured to be above ``min_sep*lambda/D``.
            IDL parameter: ``MINIMUM_SEPARATION_INPUT``
        annuli_width : float, optional
            Annuli width on which the subtraction are performed. The same for all
            annuli.
            IDL parameter: ``ANNULI_WIDTH_INPUT``
        roa : float, optional
            Ratio of the optimization area. The optimization annulus area is defined
            by ``roa * annuli_width``.
            ``roa`` is forced to ``1`` when ``opt_method="no"`` is chosen.
            IDL parameter: ``RATIO_OPT_AREA_INPUT``
        opt_method : {'no', 'total', 'lsq', 'robust'}, optional
            Method used to balance for the flux difference that exists between the
            two subtracted annuli in an optimal way during ADI.
            IDL parameter: ``OPT_METHOD_ANG_INPUT``
        nsmooth_snr : int, optional
            Number of pixels over which the radial robust standard deviation profile
            of the SNR map is smoothed to provide a global trend for the SNR map
            normalization. For ``nsmooth_snr=0`` the SNR map normalization is
            disabled.
            IDL parameter: ``NSMOOTH_SNR_INPUT``
        iwa : float or None, optional
            Inner working angle / inner radius of the first annulus taken into
            account, expressed in ``lambda/D``. If ``None``, it is chosen
            automatically between the values ``0.5``, ``4`` or ``0.25``.
            IDL parameter: ``IWA_INPUT``
        owa : float, optional
            Outer working angle / **inner** radius of the last annulus, expressed in
            ``lambda/D``. If ``None``, the value is automatically chosen based on
            the frame size.
            IDL parameter: ``OWA_INPUT``
        precision : int, optional
            Number of shifts applied to the PSF. Passed to
            ``calc_psf_shift_subpix`` , which then creates a 4D cube with shape
            (precision+1, precision+1, N, N).
            IDL parameter: ``PRECISION_INPUT``
        fast : float or bool, optional
            Size of the annuli from which the speckle noise should not be dominant
            anymore, in multiples of ``lambda/D``. If ``True``, a value of
            ``20 lambda/D`` is used, ``False`` (the default) disables the fast mode
            entirely. Above this threshold, the annuli width is set to
            ``4*annuli_width``.
            IDL parameter: ``FAST``
        homogeneous_variance : bool, optional
            If set, variance is treated as homogeneous and is calculated as a mean
            of variance in each position through time.
            IDL parameter: ``HOMOGENEOUS_VARIANCE_INPUT``
        ditimg : float, optional
            DIT for images (in sec)
            IDL Parameter: ``DITIMG_INPUT``
        ditpsf : float or None, optional
            DIT for PSF (in sec)
            IDL Parameter: ``DITPSF_INPUT``
            If set to ``None``, the value of ``ditimg`` is used.
        tnd : float, optional
            Neutral Density Transmission.
            IDL parameter: ``TND_INPUT``
        total : bool, optional
            ``total=True`` is the old behaviour (normalizing the PSF to its sum).
            IDL parameter: ``TOTAL`` (was ``MAX`` in previous releases).
        multiply_gamma : bool, optional
            Use gamma for signature computation too.
            IDL parameter: ``MULTIPLY_GAMMA_INPUT``
        verbose : bool, optional
            Print some parameter values for control.
            IDL parameter: ``VERBOSE``
        """
        super(PPAndromeda, self).__init__(locals())

    @calculates(
        "frame_final",
        "contrast_map",
        "likelihood_map",
        "snr_map",
        "stdcontrast_map",
        "snr_map_notnorm",
        "stdcontrast_map_notnorm",
        "ext_radius",
        "detection_map",
    )
    def run(self, dataset=None, nproc=1, verbose=True):
        """
        Run the ANDROMEDA algorithm for model PSF subtraction.

        Parameters
        ----------
        dataset : Dataset, optional
            Dataset to process. If not provided, ``self.dataset`` is used (as
            set when initializing this object).
        nproc : int, optional
            Number of processes to use.
        verbose : bool, optional
            Print some parameter values for control.

        """
        dataset = self._get_dataset(dataset, verbose)
        res = andromeda(
            cube=dataset.cube,
            oversampling_fact=self.oversampling_fact,
            angles=dataset.angles,
            psf=dataset.psf,
            filtering_fraction=self.filtering_fraction,
            min_sep=self.min_sep,
            annuli_width=self.annuli_width,
            roa=self.roa,
            opt_method=self.opt_method,
            nsmooth_snr=self.nsmooth_snr,
            iwa=self.iwa,
            owa=self.owa,
            precision=self.precision,
            fast=self.fast,
            homogeneous_variance=self.homogeneous_variance,
            ditimg=self.ditimg,
            ditpsf=self.ditpsf,
            tnd=self.tnd,
            total=self.total,
            multiply_gamma=self.multiply_gamma,
            nproc=nproc,
            verbose=verbose,
        )

        self.contrast_map = res[0]
        self.likelihood_map = res[5]
        self.ext_radius = res[6]

        # normalized/not normalized depending on nsmooth:
        self.snr_map = res[2]
        self.stdcontrast_map = res[4]
        if self.nsmooth_snr != 0:
            self.snr_map_notnorm = res[1]
            self.stdcontrast_map_notnorm = res[3]

        # general attributes:
        self.frame_final = self.contrast_map
        self.detection_map = self.snr_map

    def make_snr_map(self, *args, **kwargs):
        """
        Do nothing. For Andromeda, ``snr_map`` is calculated by ``run()``.

        Note
        ----
        The ``@calculates`` decorator is not present in this function
        definition, so ``self._get_calculations`` does not mark ``snr_map`` as
        created by this function.

        """
        pass


class PPFMMF(PostProc):
    """Post-processing forward model matching filter algorithm."""

    def __init__(
        self,
        dataset=None,
        min_radius=None,
        max_radius=None,
        model="KLIP",
        var="FR",
        param={"ncomp": 20, "tolerance": 5e-3, "delta_rot": 0.5},
        crop=5,
        imlib="vip-fft",
        interpolation="lanczos4",
        nproc=1,
        verbose=True,
    ):
        """
        Set up the FMMF algorithm parameters.

        Parameters
        ----------
        dataset : Dataset object
            A Dataset object to be processed.
        min_radius : int,optional
            Center radius of the first annulus considered in the FMMF detection
            map estimation. The radius should be larger than half
            the value of the 'crop' parameter . Default is None which
            corresponds to one FWHM.
        max_radius : int
            Center radius of the last annulus considered in the FMMF detection
            map estimation. The radius should be smaller or equal to half the
            size of the image minus half the value of the 'crop' parameter.
            Default is None which corresponds to half the size of the image
            minus half the value of the 'crop' parameter.
        model: {'KLIP', 'LOCI'}, optional
            Selected PSF-subtraction technique for the computation of the FMMF
            detection map. FMMF work either with KLIP or LOCI. Default is 'KLIP'.
        var: {'FR', 'FM', 'TE'}, optional
            Model used for the residual noise variance estimation used in the
            matched filtering (maximum likelihood estimation of the flux and SNR).
            Three different approaches are proposed:

            * 'FR': consider the pixels in the selected annulus with a width equal
              to asize but separately for every frame.
            * 'FM': consider the pixels in the selected annulus with a width
              equal to asize but separately for every frame. Apply a mask one FWHM
              on the selected pixel and its surrounding.
            * 'TE': rely on the method developped in PACO to estimate the
              residual noise variance (take the pixels in a region of one FWHM
              arround the selected pixel, considering every frame in the
              derotated cube of residuals except for the selected frame)
        param: dict, optional
            Dictionnary regrouping the parameters used by the KLIP (ncomp and
            delta_rot) or LOCI (tolerance and delta_rot) PSF-subtraction
            technique:

            * ncomp : int, optional. Number of components used for the low-rank
              approximation of the speckle field. Default is 20.
            * tolerance: float, optional. Tolerance level for the approximation of
              the speckle field via a linear combination of the reference images in
              the LOCI algorithm. Default is 5e-3.
            * delta_rot : float, optional. Factor for tunning the parallactic angle
              threshold, expressed in FWHM. Default is 0.5 (excludes 0.5xFHWM on each
              side of the considered frame).
        crop: int, optional
            Part of the PSF template considered in the estimation of the FMMF
            detection map. Default is 5.
        imlib : str, optional
            Parameter used for the derotation of the residual cube. See the
            documentation of the ``vip_hci.preproc.frame_rotate`` function.
        interpolation : str, optional
            Parameter used for the derotation of the residual cube. See the
            documentation of the ``vip_hci.preproc.frame_rotate`` function.
        nproc : int or None, optional
            Number of processes for parallel computing. By default ('nproc=1')
            the algorithm works in single-process mode. If set to None, nproc
            is automatically set to half the number of available CPUs.
        verbose : bool, optional
            If True prints to stdout intermediate info.

        """
        super(PPFMMF, self).__init__(locals())

    @calculates("frame_final", "snr_map")
    def run(
        self,
        dataset=None,
        model="KLIP",
        nproc=1,
        verbose=True,
    ):
        """
        Run the post-processing FMMF algorithm for model PSF subtraction.

        Parameters
        ----------
        dataset : Dataset object
            An Dataset object to be processed.
        model: {'KLIP', 'LOCI'}, optional
            If you want to change the default model. See documentation above for more
            information.
        nproc : None or int, optional
            Number of processes for parallel computing. If None the number of
            processes will be set to cpu_count()/2. By default the algorithm works
            in single-process mode.
        verbose : bool, optional
            If True prints to stdout intermediate info.

        """
        dataset = self._get_dataset(dataset, verbose)

        if dataset.fwhm is None:
            raise ValueError("`fwhm` has not been set")

        if self.model != model:
            self.model = model

        res = fmmf(
            cube=dataset.cube,
            pa=dataset.angles,
            psf=dataset.psf,
            fwhm=dataset.fwhm,
            min_r=self.min_radius,
            max_r=self.max_radius,
            model=self.model,
            var=self.var,
            param=self.param,
            crop=self.crop,
            imlib=self.imlib,
            interpolation=self.interpolation,
            nproc=nproc,
            verbose=verbose,
        )

        self.frame_final, self.snr_map = res
