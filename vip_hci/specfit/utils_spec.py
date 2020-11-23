#! /usr/bin/env python

"""
Utility functions for spectral fitting.
"""

__author__ = 'Valentin Christiaens'
__all__ = ['akaike',
           'blackbody',
           'combine_spec_corrs',
           'convert_F_units',
           'extinction',
           'find_nearest',
           'inject_em_line',
           'mj_from_rj_and_logg',
           'nrefrac']

import astropy.constants as c
import numpy as np
from scipy.signal import gaussian
        
def akaike(LnL, k):
    """
    Computes the Akaike Information Criterion: 2k-2ln(L),
    where k is the number of estimated parameters in the model and LnL is the 
    max ln-likelihood for the model.
    """
    return 2*k-2*LnL  


def blackbody(lbda, T): 
    """
    Assumes lbda is a wavelength vector in micrometers.
    """
    fac = 2*c.h.value*(c.c.value**2)/(np.power(lbda*1e-6,5))
    div = (1/(np.exp((c.h.value*c.c.value)/((lbda*1e-6)*c.k_B.value*T))-1))
    return fac*div


def combine_spec_corrs(arr_list):
    """ Combines the spectral correlation matrices of different instruments 
    into a single square matrix (required for input of spectral fit).
    
    Parameters
    ----------
    arr_list : list or tuple of numpy ndarrays
        List/tuple containing the distinct square spectral correlation matrices 
        OR ones (for independent photometric measurements). 

    Returns
    -------
    combi_corr : numpy 2d ndarray
        2d square ndarray representing the combined spectral correlation.
        
    """
    n_arr = len(arr_list)
    
    size = 0
    for nn in range(n_arr):
        if isinstance(arr_list[nn],np.ndarray):
            if arr_list[nn].ndim != 2:
                raise TypeError("Arrays of the tuple should be 2d")
            elif arr_list[nn].shape[0] != arr_list[nn].shape[1]:
                raise TypeError("Arrays of the tuple should be square")
            size+=arr_list[nn].shape[0]
        elif arr_list[nn] == 1:
            size+=1
        else:
            raise TypeError("Tuple can only have square 2d arrays or ones")
            
    combi_corr = np.zeros([size,size])
    
    size_tmp = 0
    for nn in range(n_arr):
        if isinstance(arr_list[nn],np.ndarray):
            mm = arr_list[nn].shape[0]
            combi_corr[size_tmp:size_tmp+mm,size_tmp:size_tmp+mm]=arr_list[nn]
            size_tmp+=mm
        elif arr_list[nn] == 1:
            combi_corr[size_tmp,size_tmp]=1
            size_tmp+=1      
        
    return combi_corr


def convert_F_units(F, lbda, in_unit='cgs', out_unit='si'):
    """
    Function to convert Flux density between [ergs s^-1 cm^-2 um^-1], 
    [W m^-2 um^-1] and [Jy].

    Parameters:
    -----------
    F: float or 1d array
        Flux
    lbda: float or 1d array
        Wavelength of the flux (in um)
    in_unit: str, opt, {"si", "cgs", "jy", "cgsA"} 
        Input flux units. 
        'si': W/m^2/mu; 
        'cgs': ergs/s/cm^2/mu
        'jy': janskys
        'cgsA': erg/s/cm^2/AA 
    out_unit: str, opt {"si", "cgs", "jy"}
        Output flux units.
        
    Returns:
    --------
    Flux in output units.
    """

    if in_unit == 'cgs':
        new_F = (F*1e23*np.power(lbda,2))/(c.c.value*1e6) # convert to jy
    elif in_unit == 'cgsA':
        new_F = (F*1e27*np.power(lbda,2))/(c.c.value*1e6) # convert to jy
    elif in_unit == 'si':
        new_F = (F*1e26*np.power(lbda,2))/(c.c.value*1e6) # convert to jy
    elif in_unit == "jy":
        new_F=F
    else:
        raise TypeError("in_unit not recognized, try either 'cgs', 'si' or 'jy'.")        
    if out_unit == 'jy':
        return new_F
    elif out_unit == 'cgs':
        return new_F*1e-23*c.c.value*1e6/np.power(lbda,2)
    elif out_unit == 'si':
        return new_F*1e-26*c.c.value*1e6/np.power(lbda,2)
    else:
        raise TypeError("out_unit not recognized, try either 'cgs', 'si' or 'jy'.")  




def extinction(lbda, AV, RV=3.1):
    """
    Calculates the A(lambda) extinction for a given combination of A_V and R_V.
    If R_V is not provided, assumes an ISM value of R_V=3.1
    Uses the Cardelli et al. (1989) empirical formulas.
    
    Parameters
    ----------
    lbda : 1d np.ndarray
        Array with the wavelengths (um) for which the extinction is calculated.
    AV : float
        Extinction (mag) in the V band.
    RV : float, opt
        Reddening in the V band: R_V = A_V / E(B-V)
        
    Returns
    -------
    Albda: 1d np.ndarray
        Extinction (mag) at wavelengths lbda.
    """

    xx = 1./lbda
    yy = xx - 1.82

    a_c = np.zeros_like(xx)
    b_c = np.zeros_like(xx)

    indices = np.where(xx < 1.1)[0]

    if len(indices) > 0:
        a_c[indices] = 0.574*np.power(xx[indices], 1.61)
        b_c[indices] = -0.527*np.power(xx[indices], 1.61)

    indices = np.where(xx >= 1.1)[0]

    if len(indices) > 0:
        a_c[indices] = 1. + 0.17699*yy[indices] - 0.50447*yy[indices]**2 - \
                       0.02427*yy[indices]**3 + 0.72085*yy[indices]**4 + \
                       0.01979*yy[indices]**5 - 0.77530*yy[indices]**6 + \
                       0.32999*yy[indices]**7

        b_c[indices] = 1.41338*yy[indices] + 2.28305*yy[indices]**2 + \
                       1.07233*yy[indices]**3 - 5.38434*yy[indices]**4 - \
                       0.62251*yy[indices]**5 + 5.30260*yy[indices]**6 - \
                       2.09002*yy[indices]**7

    return AV * (a_c + b_c/RV)


def find_nearest(array, value, output='index', constraint=None, n=1):
    """
    Function to find the indices, and optionally the values, of an array's n 
    closest elements to a certain value.
    
    Parameters
    ----------
    array: 1d numpy array or list
        Array in which to check the closest element to value.
    value: float
        Value for which the algorithm searches for the n closest elements in 
        the array.
    output: str, opt {'index','value','both' }
        Set what is returned
    constraint: str, opt {None, 'ceil', 'floor'}
        If not None, will check for the closest element larger than value (ceil)
        or closest element smaller than value (floor).
    n: int, opt
        Number of elements to be returned, sorted by proximity to the value.
        Default: only the closest value is returned.
    
    Returns:
    --------
    Either:
    1) index/indices of the closest n value(s) in the array;
    2) the closest n value(s) in the array, 
    3) both 1) and 2). 
    By default, only returns the index/indices
    
    Possible constraints: 'ceil', 'floor', None ("ceil" will return the closest 
    element with a value greater than 'value', "floor" the opposite)
    """
    if isinstance(array, np.ndarray):
        pass
    elif isinstance(array, list):
        array = np.array(array)
    else:
        raise ValueError("Input type for array should be np.ndarray or list.")
    
    if constraint is None:
        fm = np.absolute(array-value)
        idx = fm.argsort()[:n]
    elif constraint == 'floor' or constraint == 'ceil': 
        indices = np.arange(len(array),dtype=np.int32)
        if constraint == 'floor':
            fm = -(array-value)
        else:
            fm = array-value
        crop_indices = indices[np.where(fm>0)]
        fm = fm[np.where(fm>0)]
        idx = fm.argsort()[:n]
        idx = crop_indices[idx]
        if len(idx)==0:
            raise ValueError("No indices match the constraint")
    else:
        raise ValueError("Constraint not recognised")

    if n == 1:
        idx = idx[0]

    if output=='index': return idx
    elif output=='value': return array[idx]
    else: return array[idx], idx


def inject_em_line(wl, flux, lbda, spec, width=None, em=True, height=0.1):
    """
    Injects an emission (or absorption) line in a spectrum. The line will be 
    injected assuming a gaussian profile with either the provided FWHM (in mu) 
    or (if not provided) set to the equivalent width of the line.
    Height is the ratio to peak where the line width is considered. E.g. if 
    height=10%, the width will be the full width at 10% maximum.
    """
    # convert ew, assuming it's in mu
    idx_mid = find_nearest(lbda, wl)
    
    nch = len(lbda)
    dlbda = (lbda[idx_mid+1]-lbda[idx_mid-1])/2
    
    # estimate model continuum level using adjacent channels in the spectrum
    lbda_b0 = 0.99*lbda[idx_mid]
    idx_b0 = find_nearest(lbda, lbda_b0, constraint='floor')-1
    lbda_b1 = 0.995*lbda[idx_mid]
    idx_b1 = find_nearest(lbda, lbda_b1, constraint='floor')
    lbda_r1 = 1.01*lbda[idx_mid] 
    idx_r1 = find_nearest(lbda, lbda_r1, constraint='ceil')+1
    lbda_r0 = 1.005*lbda[idx_mid] 
    idx_r0 = find_nearest(lbda, lbda_r0, constraint='ceil')
    if idx_b0<0 or idx_r1>nch-1:
        raise ValueError("The line is too close from the edge of the spectrum")
    spec_b = spec[idx_b0:idx_b1+1]
    spec_r = spec[idx_r0:idx_r1+1]
    cont = np.median(np.concatenate((spec_b,spec_r)))
    
    if width is None:
        # infer ew
        ew = flux/cont
        # infer gaussian profile assuming FWHM = EW
        stddev = ew/(2*np.sqrt(2*np.log(1/height)))
    else:
        stddev = width/(2*np.sqrt(2*np.log(1/height)))
        
    win_sz = int((5*stddev)/dlbda)

    if win_sz%2==0:
        win_sz+=1
    idx_ini = int(idx_mid - (win_sz-1)/2)
    if idx_ini<0:
        msg = "idx ini for line injection negative: try smaller line flux"
        msg+= " than: {} W/m2 (surface flux)"
        raise ValueError(msg.format(flux))
    elif idx_ini+win_sz>len(spec):
        msg = "idx fin for line injection larger than spec length: try smaller"
        msg += " line flux than: {} W/m2 (surface flux)"
        raise ValueError(msg.format(flux))
    if win_sz<1:
        raise ValueError("window size for line injection = {}<1".format(win_sz))
    elif win_sz==1:
        gaus = flux/dlbda
    else:
        gaus = gaussian(win_sz,stddev/dlbda)
        # scale the gaussian to contain exactly required flux
        dlbda_tmp = lbda[idx_ini+1:idx_ini+win_sz+1]-lbda[idx_ini:idx_ini+win_sz]
        gaus = flux*gaus/(np.sum(gaus)*dlbda_tmp)

    
    if em:
        spec[idx_ini:idx_ini+win_sz] += gaus
    else:
        spec[idx_ini:idx_ini+win_sz] -= gaus
    
    return spec
    

def mj_from_rj_and_logg(rp, logg):
    """
    Estimates a planet mass in Jupiter mass for a given radius in Jupiter 
    radius and the log of the surface gravity. 
    """    
    surf_g = 1e-2 * 10.**logg  # (m s-2)

    rp *= c.R_jup.value # (m)

    mp = surf_g*rp**2/c.G.value # (kg)
    mp /= c.M_jup.value  # (Mjup)

    return mp


def nrefrac(wavelength, density=1.0):
   """Calculate refractive index of air from Cauchy formula.

   Input: wavelength in Angstrom, density of air in amagat (relative to STP,
   e.g. ~10% decrease per 1000m above sea level).
   Returns N = (n-1) * 1.e6. 
   Credit: France Allard.
   """

   # The IAU standard for conversion from air to vacuum wavelengths is given
   # in Morton (1991, ApJS, 77, 119). For vacuum wavelengths (VAC) in
   # Angstroms, convert to air wavelength (AIR) via: 

   #  AIR = VAC / (1.0 + 2.735182E-4 + 131.4182 / VAC^2 + 2.76249E8 / VAC^4)

   try:
       wl = np.array(wavelength)
   except TypeError:
       return None

   wl2inv = (1e4/wl)**2
   refracstp = 272.643 + 1.2288 * wl2inv  + 3.555e-2 * wl2inv**2
   return density * refracstp