import warnings

import astropy.constants as const
import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time

from sora.body import Body
from sora.ephem import EphemKernel, EphemJPL, EphemPlanete, EphemHorizons
from sora.star import Star
from sora.config.decorators import deprecated_alias

__all__ = ['occ_params', 'prediction']


def occ_params(star, ephem, time, n_recursions=5, max_tdiff=None):
    """Calculates the parameters of the occultation, as instant, CA, PA.

    Parameters:
        star (Star): The coordinate of the star in the same reference frame as 
          the ephemeris. It must be a Star object.
        ephem (Ephem): object ephemeris. It must be an Ephemeris object.
        time (Time): Time close to occultation epoch to calculate occultation
          parameters.
        n_recursions (int): The number of attempts to try obtain prediction 
          parameters in case the event is outside the previous range of time 
          (Default=5).
        max_tdiff (int): Maximum difference from given time it will attempt to 
          identify the occultation, in minutes. If given, 'n_recursions' is 
          ignored (Default=None).

    Returns:
        instant of CA (Time): Instant of Closest Approach.
        CA (arcsec): Distance of Closest Approach.
        PA (deg): Position Angle at Closest Approach.
        vel (km/s): Velocity of the occultation.
        dist (AU): the object geocentric distance.

    """

    n_recursions = int(n_recursions)
    n_iter = n_recursions
    if type(star) != Star:
        raise ValueError('star must be a Star object')
    if type(ephem) not in [EphemKernel, EphemJPL, EphemPlanete, EphemHorizons]:
        raise ValueError('ephem must be an Ephemeris object')

    time = Time(time)
    coord = star.geocentric(time)

    if type(ephem) == EphemPlanete:
        ephem.fit_d2_ksi_eta(coord, verbose=False)

    def calc_min(time0, time_interval, delta_t, n_recursions=5, max_tdiff=None):
        if max_tdiff is not None:
            max_t = u.Quantity(max_tdiff, unit=u.min)
            if np.absolute((time0 - time).sec*u.s) > max_t - time_interval*u.s:
                raise ValueError('Occultation is farther than {} from given time'.format(max_t))
        if n_recursions == 0:
            raise ValueError('Occultation is farther than {} min from given time'.format(n_iter*time_interval/60))
        tt = time0 + np.arange(-time_interval, time_interval, delta_t)*u.s
        ksi, eta = ephem.get_ksi_eta(tt, coord)
        dd = np.sqrt(ksi*ksi+eta*eta)
        min = np.argmin(dd)
        if min < 2:
            return calc_min(time0=tt[0], time_interval=time_interval, delta_t=delta_t,
                            n_recursions=n_recursions-1, max_tdiff=max_tdiff)
        elif min > len(tt) - 2:
            return calc_min(time0=tt[-1], time_interval=time_interval, delta_t=delta_t,
                            n_recursions=n_recursions-1, max_tdiff=max_tdiff)

        ksi, eta = ephem.get_ksi_eta(tt[min], coord)
        dd = np.sqrt(ksi*ksi+eta*eta)
        dist = ephem.get_position(tt[min]).distance
        ca = np.arcsin(dd*u.km/dist).to(u.arcsec)
        pa = (np.arctan2(ksi, eta)*u.rad).to(u.deg)
        if pa < 0*u.deg:
            pa = pa + 360*u.deg

        ksi2, eta2 = ephem.get_ksi_eta(tt[min]+1*u.s, coord)
        dksi = ksi2-ksi
        deta = eta2-eta
        vel = np.sqrt(dksi**2 + deta**2)/1
        vel = vel*np.sign(dksi)*(u.km/u.s)

        return tt[min], ca, pa, vel, dist.to(u.AU)

    if isinstance(ephem, (EphemJPL, EphemHorizons)):
        tmin = calc_min(time0=time, time_interval=600, delta_t=4, n_recursions=5, max_tdiff=max_tdiff)[0]
        return calc_min(time0=tmin, time_interval=8, delta_t=0.02, n_recursions=5, max_tdiff=max_tdiff)
    else:
        return calc_min(time0=time, time_interval=600, delta_t=0.02, n_recursions=5, max_tdiff=max_tdiff)


@deprecated_alias(log='verbose')  # remove this line in v1.0
def prediction(time_beg, time_end, body=None, ephem=None, mag_lim=None, catalogue='gaiaedr3', step=60, divs=1, sigma=1,
               radius=None, verbose=True):
    """Predicts stellar occultations.

    Parameters:
        time_beg (str,Time): Initial time for prediction (required).
        time_end (str,Time): Final time for prediction (required).
        body (Body, str): Object that will occult the stars. It must be a Body 
          object or its name to search in the Small Body Database.
        ephem (Ephem): object ephemeris. It must be an Ephemeris object.
        mag_lim (int,float): Faintest Gmag for search
        catalogue (str): The catalogue to download data. It can be 'gaiadr2' or 
          'gaiaedr3'.
        step (number): step, in seconds, of ephem times for search
        divs (int): number of regions the ephemeris will be splitted for better 
          search of occultations.
        sigma (number): ephemeris error sigma for search off-Earth.
        radius (number): The radius of the body. It is important if not defined 
          in body or ephem.
        verbose (bool): To show what is being done at the moment.

    Important:
        When instantiating with "body" and "ephem", the user may call the function 
          in 3 ways:

          1) With "body" and "ephem".

          2) With only "body". In this case, the "body" parameter must be a Body 
          object and have an ephemeris associated (see Body documentation).

          3) With only "ephem". In this case, the "ephem" parameter must be one of 
          the Ephem Classes and have a name (see Ephem documentation) to search 
          for the body in the Small Body Database.

    Returns:
        predict (PredictionTable): PredictionTable with the occultation params 
          for each event.

    """
    from astroquery.vizier import Vizier
    from .table import PredictionTable

    # generate ephemeris
    if body is None and ephem is None:
        raise ValueError('"body" and/or "ephem" must be given.')
    if body is not None:
        if not isinstance(body, (str, Body)):
            raise ValueError('"body" must be a string with the name of the object or a Body object')
        if isinstance(body, str):
            body = Body(name=body, mode='sbdb')
    if ephem is not None:
        if body is not None:
            body.ephem = ephem
            ephem = body.ephem
    else:
        ephem = body.ephem
    if not isinstance(ephem, EphemKernel):
        raise TypeError('At the moment prediction only works with EphemKernel')
    time_beg = Time(time_beg)
    time_end = Time(time_end)
    intervals = np.round(np.linspace(0, (time_end-time_beg).sec, divs+1))

    # define catalogue parameters
    allowed_catalogues = ['gaiadr2', 'gaiaedr3']
    if catalogue not in allowed_catalogues:
        raise ValueError('Catalogue {} is not one of the allowed catalogues {}'.format(catalogue, allowed_catalogues))
    vizpath = {'gaiadr2': 'I/345/gaia2', 'gaiaedr3': 'I/350/gaiaedr3'}[catalogue]
    cat_name = {'gaiadr2': 'Gaia-DR2', 'gaiaedr3': 'Gaia-EDR3'}[catalogue]
    columns = {'gaiadr2': ['Source', 'RA_ICRS', 'DE_ICRS', 'pmRA', 'pmDE', 'Plx', 'RV', 'Epoch', 'Gmag'],
               'gaiaedr3': ['Source', 'RA_ICRS', 'DE_ICRS', 'pmRA', 'pmDE', 'Plx', 'RVDR2', 'Epoch', 'Gmag']}[catalogue]
    kwds = {'columns': columns, 'row_limit': 10000000, 'timeout': 600}
    if mag_lim:
        kwds['column_filters'] = {"Gmag": "<{}".format(mag_lim)}
    vquery = Vizier(**kwds)

    # determine suitable divisions for star search
    if radius is None:
        try:
            radius = ephem.radius  # for v1.0, change to body.radius
        except AttributeError:
            radius = 0
            warnings.warn('"radius" not given or found in body or ephem. Considering it to be zero.')
        if np.isnan(radius):
            radius = 0
    radius = u.Quantity(radius, unit=u.km)

    radius_search = radius + const.R_earth

    if verbose:
        print('Ephemeris was split in {} parts for better search of stars'.format(divs))

    # makes predictions for each division
    occs = []
    for i in range(divs):
        dt = np.arange(intervals[i], intervals[i+1], step)*u.s
        nt = time_beg + dt
        if verbose:
            print('\nSearching occultations in part {}/{}'.format(i+1, divs))
            print("Generating Ephemeris between {} and {} ...".format(nt.min(), nt.max()))
        ncoord = ephem.get_position(nt)
        ra = np.mean([ncoord.ra.min().deg, ncoord.ra.max().deg])
        dec = np.mean([ncoord.dec.min().deg, ncoord.dec.max().deg])
        mindist = (np.arcsin(radius_search/ncoord.distance).max() +
                   sigma*np.max([ephem.error_ra.value, ephem.error_dec.value])*u.arcsec)
        width = ncoord.ra.max() - ncoord.ra.min() + 2*mindist
        height = ncoord.dec.max() - ncoord.dec.min() + 2*mindist
        pos_search = SkyCoord(ra*u.deg, dec*u.deg)

        if verbose:
            print('Downloading stars ...')
        catalogue = vquery.query_region(pos_search, width=width, height=height, catalog=vizpath, cache=False)
        if len(catalogue) == 0:
            print('    No star found. The region is too small or VizieR is out.')
            continue
        catalogue = catalogue[0]
        if verbose:
            print('    {} {} stars downloaded'.format(len(catalogue), cat_name))
            print('Identifying occultations ...')
        pm_ra_cosdec = catalogue['pmRA'].quantity
        pm_ra_cosdec[np.where(np.isnan(pm_ra_cosdec))] = 0*u.mas/u.year
        pm_dec = catalogue['pmDE'].quantity
        pm_dec[np.where(np.isnan(pm_dec))] = 0*u.mas/u.year
        stars = SkyCoord(catalogue['RA_ICRS'].quantity, catalogue['DE_ICRS'].quantity, distance=np.ones(len(catalogue))*u.pc,
                         pm_ra_cosdec=pm_ra_cosdec, pm_dec=pm_dec, obstime=Time(catalogue['Epoch'].quantity.value, format='jyear'))
        prec_stars = stars.apply_space_motion(new_obstime=((nt[-1]-nt[0])/2+nt[0]))
        idx, d2d, d3d = prec_stars.match_to_catalog_sky(ncoord)

        dist = np.arcsin(radius_search/ncoord[idx].distance) + sigma*np.max([ephem.error_ra.value, ephem.error_dec.value])*u.arcsec \
            + np.sqrt(stars.pm_ra_cosdec**2+stars.pm_dec**2)*(nt[-1]-nt[0])/2
        k = np.where(d2d < dist)[0]
        for ev in k:
            star = Star(code=catalogue['Source'][ev], ra=catalogue['RA_ICRS'][ev]*u.deg, dec=catalogue['DE_ICRS'][ev]*u.deg,
                        pmra=catalogue['pmRA'][ev]*u.mas/u.year, pmdec=catalogue['pmDE'][ev]*u.mas/u.year,
                        parallax=catalogue['Plx'][ev]*u.mas, rad_vel=catalogue[columns[6]][ev]*u.km/u.s,
                        epoch=Time(catalogue['Epoch'][ev], format='jyear'), local=True, nomad=False, verbose=False)
            c = star.geocentric(nt[idx][ev])
            pars = [star.code, SkyCoord(c.ra, c.dec), catalogue['Gmag'][ev]]
            try:
                pars = np.hstack((pars, occ_params(star, ephem, nt[idx][ev])))
                occs.append(pars)
            except:
                pass

    meta = {'name': ephem.name or getattr(body, 'name', ''), 'time_beg': time_beg, 'time_end': time_end,
            'maglim': mag_lim, 'max_ca': mindist, 'radius': radius.to(u.km).value,
            'error_ra': ephem.error_ra.to(u.mas).value, 'error_dec': ephem.error_dec.to(u.mas).value,
            'ephem': ephem.meta['kernels'], 'catalogue': cat_name}
    if not occs:
        print('\nNo stellar occultation was found.')
        return PredictionTable(meta=meta)
    # create astropy table with the params
    occs2 = np.transpose(occs)
    time = Time(occs2[3])
    geocentric = SkyCoord([ephem.get_position(time)])
    k = np.argsort(time)
    t = PredictionTable(
        time=time[k], coord_star=occs2[1][k], coord_obj=geocentric[k], ca=[i.value for i in occs2[4][k]],
        pa=[i.value for i in occs2[5][k]], vel=[i.value for i in occs2[6][k]], mag=occs2[2][k],
        dist=[i.value for i in occs2[7][k]], source=occs2[0][k], meta=meta)
    if verbose:
        print('\n{} occultations found.'.format(len(t)))
    return t
