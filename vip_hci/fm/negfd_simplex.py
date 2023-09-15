#! /usr/bin/env python
"""
Module with simplex (Nelder-Mead) optimization for defining the flux and
position of a companion using the Negative Fake Companion.

"""
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize

from ..config import time_ini
from ..config import timing
from ..config.utils_conf import sep
from ..psfsub import pca
from .negfd_fmerit import chisquare_fd


__author__ = "V. Christiaens, O. Wertz, C. A. Gomez Gonzalez"
__all__ = ["firstguess_fd", "firstguess_fd_from_coord"]


def firstguess_fd_from_coord(
    disk_xy,
    disk_theta,
    disk_scal,
    cube,
    angs,
    disk_img,
    mask_fm,
    fmerit="sum",
    mu_sigma=None,
    f_range=None,
    psfn=None,
    algo=pca,
    algo_options={},
    imlib="skimage",
    interpolation="biquintic",
    transmission=None,
    weights=None,
    plot=False,
    verbose=True,
    save=False,
    debug=False,
    full_output=False,
    rot_options={},
):
    """

    Determine a first guess for the flux scaling of the disk image for a given \
    xy shift and rotation, by doing a simple grid search evaluating the reduced\
    chi2.

    Parameters
    ----------
    disk_xy: numpy.array
        The (x,y) shift for the disk image in the processed image.
    disk_theta: float
        The rotation angle to be applied to the disk image (after shift) in the
        processed image.
    disk_scal: float
        The spatial scaling factor to apply on the disk image (after shift and
        rotation) in the processed image.
    cube: 3d or 4d numpy ndarray
        Input ADI or ADI+IFS cube.
    angs: numpy.array
        The parallactic angle fits image expressed as a numpy.array.
    disk_img: 2d or 3d numpy ndarray
        The disk image to be injected, as a 2d ndarray (for a 3D input cube) or
        a 3d numpy array (for a 4D spectral+ADI input cube). In the latter case,
        the images should correspond to different wavelengths, and the zeroth
        shape of disk_model and cube should match.
    mask_fm: 2d numpy ndarray
        Binary mask on which to calculate the figure of merit in the processed
        image. Residuals will be minimized where mask values are 1.
    fmerit : {'sum', 'stddev'}, string optional
        Figure of merit to be used, if mu_sigma is set to None. 'sum' will find
        optimal parameters that minimize the absolute intensity residuals in
        mask_fm. 'stddev' will minimize the standard deviation of pixel
        intensity residuals in mask_fm.
    mu_sigma: tuple of 2 floats or None, opt
        If set to None: not used, and falls back to original version of the
        algorithm, using fmerit. Otherwise, should be a tuple of 2 elements,
        containing the mean and standard deviation of pixel intensities in an
        annulus encompassing most of the disk signal.
    f_range: numpy.array, optional
        The range of tested flux scaling values. If None, 30 values between 1e-1
        and 1e4 are tested, following a geometric progression.
    psfn: 2d or 3d numpy ndarray
        The normalized psf expressed as a numpy ndarray. Can be 3d for a 4d
        (spectral+ADI) input cube. This would only be used to convolve disk_img.
        Leave to None if the disk_img is already convolved.
    algo: python routine, opt {pca_annulus, pca_annular, pca, custom}
        Routine to be used to model and subtract the stellar PSF. From an input
        cube, derotation angles, and optional arguments, it should return a
        post-processed frame.
    algo_options: dict, opt
        Dictionary with additional parameters for the algorithm (e.g. ncomp,
        fwhm, asize, delta_rot, tol, min_frames_lib, max_frames_lib, cube_ref,
        svd_mode=, scaling, imlib, interpolation, collapse, if relevant).
    imlib : str, optional
        See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        By default, imlib is set to 'skimage' for NEGFC as it is faster than
        'vip-fft'. If opencv is installed, it is recommended to set imlib to
        'opencv' and interpolation to 'lanczos4'. Takes precedence over value
        provided in algo_options.
    interpolation : str, optional
        See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        If opencv is installed, it is recommended to set imlib to 'opencv' and
        interpolation to 'lanczos4'. Takes precedence over value provided in
        algo_options.
    transmission: numpy array, optional
        Array with 2 columns. First column is the radial separation in pixels.
        Second column is the off-axis transmission (between 0 and 1) at the
        radial separation given in column 1.
    weights : 1d array, optional
        If provided, the disk image flux factors will be scaled according
        to these weights before injection in the cube. Can reflect changes in
        the observing conditions throughout the sequence.
    plot: boolean, optional
        If True, the figure chi2 vs. flux is displayed.
    verbose: boolean
        If True, display intermediate info in the shell.
    save: boolean, optional
        If True, the figure chi2 vs. flux is saved as .pdf if plot is also True
    debug: bool, optional
        Whether to print details of the grid search
    full_output : bool, optional
        Whether to also return the range of fluxes tested and their chi2r
        values.

    Returns
    -------
    res : tuple
        The x shift, y shift, rotation angle and flux scaling of the disk image.
    f_range: 1d numpy.array
        [full_output=True] The range of tested flux values.
    chi2r: 1d numpy.array
        [full_output=True] The chi2r values corresponding to tested flux values.
    """

    def _grid_search_f(
        x0,
        y0,
        theta0,
        scal0,
        ch,
        cube,
        angs,
        disk_img,
        mask_fm,
        fmerit="sum",
        mu_sigma=None,
        f_range=np.geomspace(1e-1, 1e4, 30),
        psfn=None,
        algo=pca,
        algo_options={},
        imlib="skimage",
        interpolation="biquintic",
        transmission=None,
        weights=None,
        verbose=True,
        debug=False,
        rot_options=rot_options,
    ):
        chi2r = []
        if verbose:
            print("Step | flux    | chi2r")

        counter = 0
        for j, f_guess in enumerate(f_range):
            if cube.ndim == 3:
                params = (f_guess,)
            elif ch is not None and cube.ndim == 4:
                fluxes = [0] * cube.shape[0]
                fluxes[ch] = f_guess
                params = tuple(fluxes)
            else:
                raise TypeError("If cube is 4d, channel index must be provided")
            inistate = (x0, y0, theta0, scal0)
            force_params = (1, 1, 1, 1, 0)
            chi2r.append(
                chisquare_fd(
                    params,
                    cube,
                    angs,
                    disk_img,
                    mask_fm,
                    inistate,
                    force_params,
                    fmerit,
                    mu_sigma,
                    psfn,
                    algo,
                    algo_options,
                    imlib,
                    interpolation,
                    transmission,
                    weights,
                    debug,
                    rot_options,
                )
            )
            if chi2r[j] > chi2r[j - 1]:
                counter += 1
            if counter == 4:
                break
            if verbose:
                print("{}/{}   {:.3f}   {:.3f}".format(j + 1, n, f_guess,
                                                       chi2r[j]))

        return chi2r

    if len(disk_xy) != 2:
        msg = "'disk_xy' should have 2 elements"
        raise ValueError(msg)

    x0, y0 = disk_xy
    theta0 = disk_theta
    scal0 = disk_scal

    if f_range is not None:
        n = f_range.shape[0]
    else:
        n = 30
        f_range = np.geomspace(1e-1, 1e4, n)

    if cube.ndim == 3 or 'scale_list' in algo_options.keys():
        chi2r = _grid_search_f(
            x0,
            y0,
            theta0,
            scal0,
            None,
            cube,
            angs,
            disk_img,
            mask_fm,
            fmerit=fmerit,
            mu_sigma=mu_sigma,
            f_range=f_range,
            psfn=psfn,
            algo=algo,
            algo_options=algo_options,
            imlib=imlib,
            interpolation=interpolation,
            transmission=transmission,
            weights=weights,
            verbose=verbose,
            debug=debug,
            rot_options=rot_options,
        )
        chi2r = np.array(chi2r)
        f0 = f_range[chi2r.argmin()]

        if plot:
            plt.figure(figsize=(8, 4))
            plt.title("$\\chi^2_{r}$ vs flux")
            plt.xlim(f_range[0], f_range[: chi2r.shape[0]].max())
            plt.ylim(chi2r.min() * 0.95, chi2r.max() * 1.05)
            plt.plot(
                f_range[: chi2r.shape[0]],
                chi2r,
                linestyle="-",
                color="gray",
                marker=".",
                markerfacecolor="r",
                markeredgecolor="r",
            )
            plt.xlabel("flux")
            plt.ylabel(r"$\chi^2_r$")
            plt.grid("on")
        if save and plot:
            plt.savefig("chi2rVSflux.pdf")
        if plot:
            plt.show()

        res = (x0, y0, theta0, scal0, f0)

    else:
        f0 = []
        chi2r = []
        if plot:
            plt.figure(figsize=(8, 4))
            plt.title("$\\chi^2_{r}$ vs flux")
            plt.xlabel("flux")
            plt.ylabel(r"$\chi^2_{r}$")
            plt.grid("on")

        for i in range(cube.shape[0]):
            if verbose:
                print("Processing spectral channel {}...".format(i))
            chi2r_tmp = _grid_search_f(
                x0,
                y0,
                theta0,
                scal0,
                i,
                cube,
                angs,
                disk_img[i],
                mask_fm,
                fmerit=fmerit,
                mu_sigma=mu_sigma,
                f_range=f_range,
                psfn=psfn,
                algo=algo,
                algo_options=algo_options,
                imlib=imlib,
                interpolation=interpolation,
                transmission=transmission,
                weights=weights,
                verbose=verbose,
                debug=debug,
                **rot_options
            )
            chi2r.append(chi2r_tmp)
            chi2r_tmp = np.array(chi2r_tmp)
            f0.append(f_range[chi2r_tmp.argmin()])
            if verbose:
                msg = r"... optimal grid flux: {:.3f} ($\chi^2_r$ = {:.1f})"
                print(msg.format(f0[i], np.amin(chi2r_tmp)))

            if i == 0:
                min_chi2r = chi2r_tmp.min()
                max_chi2r = chi2r_tmp.max()
                fmax = f0[i]
            else:
                if min_chi2r > chi2r_tmp.min():
                    min_chi2r = chi2r_tmp.min()
                if max_chi2r < chi2r_tmp.max():
                    max_chi2r = chi2r_tmp.max()
                if fmax < f0[i]:
                    fmax = f0[i]

            if plot:
                plt.plot(
                    f_range[: chi2r_tmp.shape[0]],
                    chi2r_tmp,
                    linestyle="-",
                    marker=".",
                    markerfacecolor="r",
                    markeredgecolor="r",
                    label="ch. {}".format(i),
                )

        if plot:
            plt.xlim(f_range[0], f_range[: chi2r_tmp.shape[0]].max())
            plt.ylim(min_chi2r * 0.9, max_chi2r * 1.1)
            plt.legend()
        if save and plot:
            plt.savefig("chi2rVSflux.pdf")
        if plot:
            plt.show()

        res = tuple([x0, y0, theta0, scal0] + f0)
        res = tuple(res)

    if full_output:
        return res, f_range, chi2r
    else:
        return res


def firstguess_fd_simplex(
    p,
    cube,
    angs,
    disk_img,
    mask_fm,
    fmerit="sum",
    mu_sigma=None,
    force_params=None,
    options=None,
    psfn=None,
    algo=pca,
    algo_options={},
    imlib="skimage",
    interpolation="biquintic",
    transmission=None,
    weights=None,
    plot=False,
    verbose=False,
    rot_options={},
):
    """

    Determine the position of a companion using the negative fake companion \
    technique and a standard minimization algorithm (Default=Nelder-Mead).

    Parameters
    ----------
    p : np.array
        Estimate of the x shift, y shift, rotation angle and flux scaling of the
        disk image.
    cube: 3d or 4d numpy ndarray
        Input ADI or ADI+IFS cube.
    angs: numpy.array
        The parallactic angle fits image expressed as a numpy.array.
    disk_img: 2d or 3d numpy ndarray
        The disk image to be injected, as a 2d ndarray (for either 3D or 4D
        input cubes) or a 3d numpy array (for a 4D spectral+ADI input cube). In
        the latter case, the images should correspond to different wavelengths,
        and the zeroth shape of disk_model and cube should match.
    mask_fm: 2d numpy ndarray
        Binary mask on which to calculate the figure of merit in the processed
        image. Residuals will be minimized where mask values are 1.
    fmerit : {'sum', 'stddev'}, string optional
        Figure of merit to be used, if mu_sigma is set to None. 'sum' will find
        optimal parameters that minimize the absolute intensity residuals in
        mask_fm. 'stddev' will minimize the standard deviation of pixel
        intensity residuals in mask_fm.
    mu_sigma: tuple of 2 floats or None, opt
        If set to None: not used, and falls back to original version of the
        algorithm, using fmerit. Otherwise, should be a tuple of 2 elements,
        containing the mean and standard deviation of pixel intensities in an
        annulus encompassing most of the disk signal, with the standard
        deviation then converted into a proxy for noise.
    force_params: None or list/tuple of bool, optional
        If not None, list/tuple of bool corresponding to parameters to fix.
    options: dict, optional
        The scipy.optimize.minimize options.
    psfn: 2d or 3d numpy ndarray
        The normalized psf expressed as a numpy ndarray. Can be 3d for a 4d
        (spectral+ADI) input cube. This would only be used to convolve disk_img.
        Leave to None if the disk_img is already convolved.
    algo: python routine, opt {pca_annulus, pca_annular, pca, custom}
        Routine to be used to model and subtract the stellar PSF. From an input
        cube, derotation angles, and optional arguments, it should return a
        post-processed frame.
    algo_options: dict, opt
        Dictionary with additional parameters for the algorithm (e.g. ncomp,
        fwhm, asize, delta_rot, tol, min_frames_lib, max_frames_lib, cube_ref,
        svd_mode=, scaling, imlib, interpolation, collapse, if relevant).
    imlib : str, optional
        See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        By default, imlib is set to 'skimage' for NEGFC as it is faster than
        'vip-fft'. If opencv is installed, it is recommended to set imlib to
        'opencv' and interpolation to 'lanczos4'. Takes precedence over value
        provided in algo_options.
    interpolation : str, optional
        See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        If opencv is installed, it is recommended to set imlib to 'opencv' and
        interpolation to 'lanczos4'. Takes precedence over value provided in
        algo_options.
    transmission: numpy array, optional
        Array with 2 columns. First column is the radial separation in pixels.
        Second column is the off-axis transmission (between 0 and 1) at the
        radial separation given in column 1.
    weights : 1d array, optional
        If provided, the disk image flux factors will be scaled according
        to these weights before injection in the cube. Can reflect changes in
        the observing conditions throughout the sequence.
    verbose : boolean, optional
        If True, additional information is printed out.
    **kwargs: optional
        Optional arguments to the scipy.optimize.minimize function

    Returns
    -------
    solu : scipy.optimize.minimize solution object
        The solution of the minimization algorithm.

    """
    if verbose:
        print("\nNelder-Mead minimization is running...")

    if force_params is not None:
        p_t = []
        p_ini = []
        for i in range(len(p)):
            if force_params[i]:
                p_ini.append(p[i])
            else:
                p_t.append(p[i])
        p_t = tuple(p_t)
        p_ini = tuple(p_ini)
    else:
        p_t = p
        p_ini = p
    solu = minimize(
        chisquare_fd,
        p_t,
        args=(
            cube,
            angs,
            disk_img,
            mask_fm,
            p_ini,
            force_params,
            fmerit,
            mu_sigma,
            psfn,
            algo,
            algo_options,
            imlib,
            interpolation,
            transmission,
            weights,
            False,
            rot_options,
        ),
        method="Nelder-Mead",
        options=options,
    )

    if verbose:
        print(solu)
    return solu


def firstguess_fd(
    cube,
    angs,
    disk_model,
    mask_fm,
    ini_xy=(0, 0),
    ini_theta=0,
    ini_scal=1.0,
    fmerit="sum",
    mu_sigma=None,
    f_range=None,
    psfn=None,
    algo=pca,
    algo_options={},
    imlib="skimage",
    interpolation="biquintic",
    simplex=True,
    simplex_options=None,
    transmission=None,
    weights=None,
    force_params=None,
    plot=False,
    verbose=True,
    save=False,
    full_output=False,
    rot_options={},
):
    """

    Determine a first guess for the shifts (x,y), rotation, spatial scaling and\
    flux scaling of a disk model image.

    Parameters
    ----------
    cube: 3d or 4d numpy ndarray
        Input ADI or ADI+IFS cube.
    angs: numpy.array
        The parallactic angle fits image expressed as a numpy.array.
    disk_model: numpy ndarray
        The disk image(s) to be injected, should be 2d ndarray (for a 3D input
        cube), 3d numpy array (for a 4D spectral+ADI input cube), or higher
        dimensionality for an input grid of disk models provided (the number of
        additional dimensions is inferred from the
                . In
        the latter case, the images should correspond to different wavelengths,
        and the zeroth shape of disk_model and cube should match.
    mask_fm: 2d numpy ndarray
        Binary mask on which to calculate the figure of merit in the processed
        image. Residuals will be minimized where mask values are 1.
    ini_xy: tuple or numpy array of 2 elements
        Initial estimate of the x,y shift to be applied to the disk model image.
    ini_theta: float
        Initial estimate of the rotation angle to be applied to the disk model
        image (after shift).
    ini_scal: float
        Initial estimate of the spatial scaling factor to be applied to the disk
        model image (after shift and rotation).
    fmerit : {'sum', 'stddev'}, string optional
        Figure of merit to be used, if mu_sigma is set to None. 'sum' will find
        optimal parameters that minimize the absolute intensity residuals in
        mask_fm. 'stddev' will minimize the standard deviation of pixel
        intensity residuals in mask_fm.
    mu_sigma: tuple of 2 floats or None, opt
        If set to None: not used, and falls back to original version of the
        algorithm, using fmerit. Otherwise, should be a tuple of 2 elements,
        containing the mean and standard deviation of pixel intensities in an
        annulus encompassing most of the disk signal.
    f_range: numpy.array, optional
        The range of tested flux scaling values. If None, 30 values between 1e-1
        and 1e4 are tested, following a geometric progression.
    psfn: 2d or 3d numpy ndarray
        The normalized psf expressed as a numpy ndarray. Can be 3d for a 4d
        (spectral+ADI) input cube. This would only be used to convolve disk_img.
        Leave to None if the disk_img is already convolved.
    algo: python routine, opt {pca, pca_annulus, pca_annular, custom}
        Routine to be used to model and subtract the stellar PSF. From an input
        cube, derotation angles, and optional arguments, it should return a
        post-processed frame.
    algo_options: dict, opt
        Dictionary with additional parameters for the algorithm (e.g. ncomp,
        fwhm, asize, delta_rot, tol, min_frames_lib, max_frames_lib, cube_ref,
        svd_mode=, scaling, imlib, interpolation, collapse, if relevant). By
        default, imlib is set to 'skimage' which is faster than 'vip-fft'. If
        opencv is installed, it is recommended to set imlib to 'opencv' and
        interpolation to 'lanczos4'.
    imlib : str, optional
        See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        By default, imlib is set to 'skimage' for NEGFC as it is faster than
        'vip-fft'. If opencv is installed, it is recommended to set imlib to
        'opencv' and interpolation to 'lanczos4'. Takes precedence over value
        provided in algo_options.
    interpolation : str, optional
        See the documentation of the ``vip_hci.preproc.frame_rotate`` function.
        If opencv is installed, it is recommended to set imlib to 'opencv' and
        interpolation to 'lanczos4'. Takes precedence over value provided in
        algo_options.
    simplex: bool, optional
        If True, the Nelder-Mead minimization is performed after the flux grid
        search.
    simplex_options: dict, optional
        The scipy.optimize.minimize options.
    transmission: numpy array, optional
        Array with 2 columns. First column is the radial separation in pixels.
        Second column is the off-axis transmission (between 0 and 1) at the
        radial separation given in column 1.
    weights : 1d array, optional
        If provided, the negative fake companion fluxes will be scaled according
        to these weights before injection in the cube. Can reflect changes in
        the observing conditions throughout the sequence. Length should match
        the temporal axis of the cube.
    force_params: None or list/tuple of bool, optional
        If not None, list/tuple of bool corresponding to parameters to fix. For
        a 4D input cube, the length of the list/tuple should be 4+nch, where nch
        is the number of spectral channels.
    plot: boolean, optional
        If True, the figure chi2 vs. flux is displayed.
    verbose: bool, optional
        If True, display intermediate info in the shell.
    save: bool, optional
        If True, the figure chi2 vs. flux is saved.
    full_output: bool, optional
        Whether to also return the chi2r, apart from the optimal parameters.

    Returns
    -------
    x_0 : float
        Optimal x shift of the model disk image
    y_0: float
        Optimal y shift of the model disk image.
    theta_0: float
        Optimal rotation angle (with respect to x axis) for the model disk
        image.
    scal_0: float
        Optimal spatial scaling factor for the model disk image.
    f_0: float
        Optimal flux scaling factor for the model disk image.
    chi2: float
        [full_output=True] Corresponding chi2r

    Note
    ----
    Polar angle is not the conventional NORTH-TO-EAST P.A., but the \
    counter-clockwise angle measured from the positive x axis.

    """
    if cube.ndim != 3 and cube.ndim != 4:
        raise TypeError("Input cube is not 3D nor 4D")

    if verbose:
        start_time = time_ini()

    ini_xy = np.array(ini_xy)

    if cube.ndim == 4:
        if psfn.ndim < 3:
            msg = "The normalized PSF should be 3D for a 4D input cube"
            raise TypeError(msg)
        if disk_model.ndim != 3:
            msg = "The disk model should be 3D for a 4D input cube"
            raise TypeError(msg)

    if weights is not None:
        if not len(weights) == cube.shape[-3]:
            msg = "Weights should have same length as temporal cube axis"
            raise TypeError(msg)

    if verbose:
        print("\n" + sep)
        msg2 = "Flux estimation for xy shift [{},{}], {}deg rotation and "
        msg2 += "{}x spatial scaling is running ..."
        print(msg2.format(ini_xy[0], ini_xy[1], ini_theta, ini_scal))

    if isinstance(mu_sigma, tuple):
        if len(mu_sigma) != 2:
            raise TypeError("If a tuple, mu_sigma must have 2 elements")

    extra_dims = cube.ndim-disk_model.ndim-1
    if extra_dims > 0:
        dim_test = disk_model.shape[:extra_dims]
        ntests = 1
        for i in range(extra_dims):
            ntests *= dim_test[i]
        all_chi2r = np.ones(ntests)
        all_succ = np.zeros(ntests)
        for c in range(ntests):
            res_c = firstguess_fd_from_coord(
                ini_xy,
                ini_theta,
                ini_scal,
                cube,
                angs,
                disk_model,
                mask_fm,
                fmerit=fmerit,
                mu_sigma=mu_sigma,
                f_range=f_range,
                psfn=psfn,
                algo=algo,
                algo_options=algo_options,
                imlib=imlib,
                interpolation=interpolation,
                transmission=transmission,
                weights=weights,
                plot=plot,
                verbose=verbose,
                full_output=True
                save=save,
                rot_options=rot_options,
            )
            res_init = res_c[0]
            if res_c[1]:
                all_chi2r[c]
                all_succ[c] = 1
            else:
                all_chi2r[]

            chi2r = res_c[-1]

            x_pre = res_init[0]
            y_pre = res_init[1]
            theta_pre = res_init[2]
            scal_pre = res_init[3]
            f_pre = res_init[4:]
    else:
        res_init = firstguess_fd_from_coord(
            ini_xy,
            ini_theta,
            ini_scal,
            cube,
            angs,
            disk_model,
            mask_fm,
            fmerit=fmerit,
            mu_sigma=mu_sigma,
            f_range=f_range,
            psfn=psfn,
            algo=algo,
            algo_options=algo_options,
            imlib=imlib,
            interpolation=interpolation,
            transmission=transmission,
            weights=weights,
            plot=plot,
            verbose=verbose,
            save=save,
            rot_options=rot_options,
        )

        x_pre = res_init[0]
        y_pre = res_init[1]
        theta_pre = res_init[2]
        scal_pre = res_init[3]
        f_pre = res_init[4:]

    if verbose:
        msg3a = "Preliminary shift, rotation and scaling guess: (x, y, theta, "
        msg3a += "scal) = ({:.1f}, {:.1f}, {:.1f}, {:.1f})"
        print(msg3a.format(x_pre, y_pre, theta_pre, scal_pre))
        msg3b = "Preliminary flux guess: "
        for z in range(len(f_pre)):
            msg3b += "{:.1f}".format(f_pre[z])
            if z < len(f_pre) - 1:
                msg3b += ", "
        print(msg3b)

    if simplex:
        if verbose:
            msg4 = "Simplex Nelder-Mead minimization, running ..."
            print(msg4)

        if simplex_options is None:
            simplex_options = {
                "xatol": 1e-6,
                "fatol": 1e-6,
                "maxiter": 800,
                "maxfev": 2000,
            }

        res = firstguess_fd_simplex(
            res_init,
            cube,
            angs,
            disk_model,
            mask_fm,
            fmerit,
            mu_sigma,
            force_params,
            simplex_options,
            psfn,
            algo,
            algo_options,
            imlib,
            interpolation,
            transmission,
            weights,
            plot,
            verbose,
            rot_options,
        )
        if force_params is not None:
            params_0 = []
            c_free = 0
            for i in range(len(res_init)):
                if force_params[i]:
                    params_0.append(res_init[i])
                else:
                    params_0.append(res.x[c_free])
                    c_free += 1
            x_0, y_0, theta_0, scal_0 = tuple(params_0[:4])
            if cube.ndim == 3:
                f_0 = params_0[4]
            else:
                f_0 = tuple(params_0[4:])
        else:
            x_0, y_0, theta_0, scal_0 = res.x[0], res.x[1], res.x[2], res.x[3]
            if cube.ndim == 3:
                f_0 = res.x[4]
            else:
                f_0 = res.x[4:]
        if verbose:
            msg5 = "Success: {}, nit: {}, nfev: {}, chi2r: {}"
            print(msg5.format(res.success, res.nit, res.nfev, res.fun))
            print("message: {}".format(res.message))

    else:
        if verbose:
            msg4 = "Simplex Nelder-Mead minimization skipped."
            print(msg4)
        x_0, y_0, theta_0, scal_0 = (x_pre, y_pre, theta_pre, scal_pre)
        if cube.ndim == 3:
            f_0 = f_pre[0]
        else:
            f_0 = f_pre

    if verbose:
        # centy, centx = frame_center(cube[0])
        # posy = y_0 + centy
        # posx = x_0 + centx
        msg6 = "Optimization result: (dx, dy, theta, scal, "
        if cube.ndim == 3:
            msg6 += "f) = ({:.2f}, {:.2f}, {:.2f}, ".format(x_0, y_0, theta_0)
            msg6 += "{:.2f}, {:.2f})".format(scal_0, f_0)
        else:
            msg6b = "({:.2f}, {:.2f}, {:.2f}, {:.2f}, ".format(
                x_0, y_0, theta_0, scal_0
            )
            for z in range(cube.shape[0]):
                msg6 += "f{}".format(z)
                msg6b += "{:.2f}".format(f_0[z])
                if z < cube.shape[0] - 1:
                    msg6 += ", "
                    msg6b += ", "
            msg6 += ")="
            msg6b += ")"
            msg6 += msg6b
        print(msg6)

    if verbose:
        print("\n", sep, "\nDONE !\n", sep)
        timing(start_time)

    if full_output:
        return x_0, y_0, theta_0, scal_0, f_0, float(res.fun)
    return x_0, y_0, theta_0, scal_0, f_0
