import warnings

import astropy.units as u
import numpy as np
from astropy.time import Time

from sora.config.decorators import deprecated_function, deprecated_alias
from sora.prediction import occ_params, PredictionTable

__all__ = ['Occultation']
warnings.simplefilter('always', UserWarning)


class Occultation:
    """Does the reduction of the occultation.

    """
    def __init__(self, star, body=None, ephem=None, time=None):
        """Instantiates the Occultation object.

        Parameters:
            star (Star, str): The coordinate of the star in the same reference 
              frame as the ephemeris. It must be a Star object or a string with 
              the coordinates of the object to search on Vizier (required).
            body (Body, str): Object that will occult the star. It must be a 
              Body object or its name to search in the Small Body Database.
            ephem (Ephem): object ephemeris. It must be an Ephemeris object or 
              a list .
            time (str, Time): Reference time of the occultation. Time does not 
              need to be exact, but needs to be within approximately 50 minutes 
              of the occultation closest approach to calculate occultation 
              parameters (required).

        Important:
            When instantiating with "body" and "ephem", the user may define the 
            Occultation in 3 ways:
            - With "body" and "ephem".
            - With only "body". In this case, the "body" parameter must be a 
              Body object and have an ephemeris associated (see Body 
              documentation).
            - With only "ephem". In this case, the "ephem" parameter must be 
              one of the Ephem Classes and have a name (see Ephem documentation) 
              to search for the body in the Small Body Database.

        """
        from sora.body import Body
        from sora.star import Star
        from .chordlist import ChordList

        if body is None and ephem is None:
            raise ValueError('"body" and/or "ephem" must be given.')
        if time is None:
            raise ValueError('"time" parameter must be given.')
        if isinstance(star, str):
            star = Star(coord=star)
        elif not isinstance(star, Star):
            raise ValueError('"star" must be a Star object or a string with coordinates of the star')
        self._star = star
        if body is not None:
            if not isinstance(body, (str, Body)):
                raise ValueError('"body" must be a string with the name of the object or a Body object')
            if isinstance(body, str):
                body = Body(name=body)
            self._body = body
        if ephem is not None:
            if body is not None:
                self.body.ephem = ephem
            else:
                if hasattr(ephem, 'name'):
                    self._body = Body(name=ephem.name, ephem=ephem)
                else:
                    raise ValueError('When only "ephem" is given, "ephem" must have a name for search.')
        try:
            ephem = self.body.ephem
        except AttributeError:
            raise ValueError('An Ephem object must be defined in Body object.')

        tca, ca, pa, vel, dist = occ_params(self.star, ephem, time)
        self.ca = ca   # Closest Approach distance
        self.pa = pa   # Position Angle at CA
        self.vel = vel  # Shadow velocity at CA
        self.dist = dist  # object distance at CA
        self.tca = tca   # Instant of CA
        self.star_diam = self.star.apparent_diameter(self.dist, verbose=False)

        meta = {
            'name': self.body.name, 'radius': self.body.radius.to(u.km).value,
            'error_ra': self.body.ephem.error_ra.to(u.mas).value, 'error_dec': self.body.ephem.error_dec.to(u.mas).value}
        self.predict = PredictionTable(
            time=[tca], coord_star=[self.star.geocentric(tca)],
            coord_obj=[self.body.ephem.get_position(tca)], ca=[ca.value], pa=[pa.value], vel=[vel.value],
            dist=[dist.value], mag=[self.star.mag['G']], source=[self.star.code], meta=meta)

        self.__observations = []
        self._chords = ChordList(star=self.star, body=self._body, time=self.tca)
        self._chords._shared_with['occultation'] = {"vel": np.absolute(self.vel), "dist": float(self.dist.AU),
                                                    "star_diam": float(self.star_diam.km)}

    @property
    def star(self):
        return self._star

    @property
    def body(self):
        return self._body

    @property
    def chords(self):
        return self._chords

    @deprecated_function(message="Please use chords.add_chord to add new observations.")
    def add_observation(self, obs, lightcurve):
        """Adds observations to the Occultation object.

        Parameters:
            obs (Observer): The Observer object to be added.
            lightcurve (LightCurve): The LightCurve object to be added.

        """
        self.chords.add_chord(name=lightcurve.name, observer=obs, lightcurve=lightcurve)

    @deprecated_function(message="Please use chords.remove_chord to remove observations.")
    def remove_observation(self, key, key_lc=None):
        """Removes an observation from the Occultation object.

        Parameters:
            key (str): The name given to Observer or LightCurve to remove from 
              the list.
            key_lc (str): In the case where repeated names are present for 
              different observations, keylc must be given for the name of the 
              LightCurve and key will be used for the name of the Observer.

        """
        try:
            self.chords.remove_chord(name=key)
        except KeyError:
            rm_list = []
            for name, chord in self.chords.items():
                if chord.observer.name == key and (key_lc is None or chord.lightcurve.name == key_lc):
                    rm_list.append(name)
            if len(rm_list) != 1:
                if len(rm_list) == 0:
                    err_mes = "No observation was identified with given keys."
                else:
                    err_mes = "More than one chord was identified. Please provide unique keys."
                raise ValueError(err_mes)
            else:
                self.chords.remove_chord(name=rm_list[0])

    @deprecated_function(message="Please use chords.")
    def observations(self):
        """ Print all the observations added to the Occultation object
            Pair (Observer, LightCurve)
        """
        print(self.chords.__repr__())

    def fit_ellipse(self, **kwargs):
        from .fitting import fit_ellipse
        Occultation.fit_ellipse.__doc__ = fit_ellipse.__doc__

        chisquare = fit_ellipse(self, **kwargs)
        return chisquare

    @property
    @deprecated_function(message="Please use chords.summary()")
    def positions(self):
        """ Calculates the position and velocity for all chords.
            Saves it into an _PositionDict object.
        """
        from functools import partial
        from .meta import _PositionDict

        if not hasattr(self, '_position'):
            self._position = _PositionDict()
        position = self._position
        if len(self.chords) == 0:
            raise ValueError('There is no observation defined for this occultation')

        pair = []
        for name, chord in self.chords.items():
            obs = chord.observer
            obs_name = obs.name
            if obs_name == '':
                obs_name = '{}_obs'.format(chord.name)
            lc = chord.lightcurve
            lc_name = lc.name
            if lc_name == '':
                lc_name = '{}_lc'.format(chord.name)
            pair.append((obs_name, lc_name))

            coord = [obs.lon, obs.lat, obs.height]
            if obs.name not in position.keys():
                position['_occ_'+obs_name] = _PositionDict(lon=obs.lon, lat=obs.lat, height=obs.height)
                position[obs_name]['_occ_lon'] = obs.lon
                position[obs_name]['_occ_lat'] = obs.lat
                position[obs_name]['_occ_height'] = obs.height
            pos_obs = position[obs_name]
            coord2 = [pos_obs['lon'], pos_obs['lat'], pos_obs['height']]
            if obs.lon != pos_obs['lon']:
                position[obs_name]['_occ_lon'] = obs.lon
            if obs.lat != pos_obs['lat']:
                position[obs_name]['_occ_lat'] = obs.lat
            if obs.height != pos_obs['height']:
                position[obs_name]['_occ_height'] = obs.height
            samecoord = (coord == coord2)

            if lc_name not in pos_obs.keys():
                pos_obs['_occ_'+lc_name] = _PositionDict()
            pos_lc = pos_obs[lc_name]

            pos_lc['_occ_status'] = chord.status()

            if hasattr(lc, 'immersion'):
                if 'immersion' not in pos_lc.keys():
                    pos_lc['_occ_immersion'] = _PositionDict(on=chord.is_able['immersion'],
                                                             enable=partial(chord.enable, time='immersion'),
                                                             disable=partial(chord.disable, time='immersion'))
                obs_im = pos_lc['immersion']
                obs_im['_occ_on'] = chord.is_able['immersion']
                do_err = False
                if samecoord and 'time' in obs_im.keys() and obs_im['time'] == lc.immersion:
                    pass
                else:
                    do_err = True
                    f1, g1, vf1, vg1 = chord.get_fg(time='immersion', vel=True)
                    obs_im['_occ_time'] = lc.immersion
                    obs_im['_occ_value'] = (round(f1, 3), round(g1, 3))
                    obs_im['_occ_vel'] = (round(vf1, 3), round(vg1, 3))
                if not do_err and 'time_err' in obs_im.keys() and obs_im['time_err'] == lc.immersion_err:
                    pass
                else:
                    fe1, ge1 = chord.get_fg(time=lc.immersion-lc.immersion_err*u.s)
                    fe2, ge2 = chord.get_fg(time=lc.immersion+lc.immersion_err*u.s)
                    obs_im['_occ_time_err'] = lc.immersion_err
                    obs_im['_occ_error'] = ((round(fe1, 3), round(ge1, 3)), (round(fe2, 3), round(ge2, 3)))

            if hasattr(lc, 'emersion'):
                pos_lc['_occ_emersion'] = _PositionDict(on=chord.is_able['emersion'],
                                                        enable=partial(chord.enable, time='emersion'),
                                                        disable=partial(chord.disable, time='emersion'))
                obs_em = pos_lc['emersion']
                do_err = False
                if samecoord and 'time' in obs_em.keys() and obs_em['time'] == lc.emersion:
                    pass
                else:
                    do_err = True
                    f1, g1, vf1, vg1 = chord.get_fg(time='emersion', vel=True)
                    obs_em['_occ_time'] = lc.emersion
                    obs_em['_occ_value'] = (round(f1, 3), round(g1, 3))
                    obs_em['_occ_vel'] = (round(vf1, 3), round(vg1, 3))
                if not do_err and 'time_err' in obs_em.keys() and obs_em['time_err'] == lc.emersion_err:
                    pass
                else:
                    fe1, ge1 = chord.get_fg(time=lc.emersion-lc.emersion_err*u.s)
                    fe2, ge2 = chord.get_fg(time=lc.emersion+lc.emersion_err*u.s)
                    obs_em['_occ_time_err'] = lc.emersion_err
                    obs_em['_occ_error'] = ((round(fe1, 3), round(ge1, 3)), (round(fe2, 3), round(ge2, 3)))

            if pos_lc['status'] == 'negative':
                if 'start_obs' not in pos_lc.keys():
                    pos_lc['_occ_start_obs'] = _PositionDict()
                obs_start = pos_lc['start_obs']
                if samecoord and 'time' in obs_start.keys() and obs_start['time'] == lc.initial_time:
                    pass
                else:
                    f, g, vf, vg = chord.get_fg(time='start', vel=True)
                    obs_start['_occ_time'] = lc.initial_time
                    obs_start['_occ_value'] = (round(f, 3), round(g, 3))
                    obs_start['_occ_vel'] = (round(vf, 3), round(vg, 3))
                if 'end_obs' not in pos_lc.keys():
                    pos_lc['_occ_end_obs'] = _PositionDict()
                obs_end = pos_lc['end_obs']
                if samecoord and 'time' in obs_end.keys() and obs_end['time'] == lc.end_time:
                    pass
                else:
                    f, g, vf, vg = chord.get_fg(time='end', vel=True)
                    obs_end['_occ_time'] = lc.end_time
                    obs_end['_occ_value'] = (round(f, 3), round(g, 3))
                    obs_end['_occ_vel'] = (round(vf, 3), round(vg, 3))

        for key in list(position):
            n = 0
            for key_lc in list(position[key]):
                if type(position[key][key_lc]) != _PositionDict:
                    continue
                if (key, key_lc) not in pair:
                    del position[key][key_lc]
                else:
                    n += 1
            if n == 0:
                del position[key]

        return self._position

    @positions.setter
    def positions(self, value):
        """
        Note:
            If the users tries to set a value to position, it must be 'on' or 'off',
            and it will be assigned to all chords.

        """
        if value not in ['on', 'off']:
            raise ValueError("Value must be 'on' or 'off' only.")
        pos = self.positions
        for key in pos.keys():
            pos[key] = value

    def check_velocities(self):
        """Prints the current velocity used by the LightCurves and its radial velocity.

        """
        if hasattr(self, 'fitted_params'):
            center = np.array([self.fitted_params['center_f'][0], self.fitted_params['center_g'][0]])
        else:
            center = np.array([0, 0])
        for name, chord in self.chords.items():
            im = getattr(chord.lightcurve, 'immersion', None)
            em = getattr(chord.lightcurve, 'emersion', None)
            if im is None and em is None:
                continue
            print('{} - Velocity used: {:.3f}'.format(name, chord.lightcurve.vel))
            if im is not None:
                vals = chord.get_fg(time=im, vel=True)
                delta = np.array(vals[0:2]) - center
                print('    Immersion Radial Velocity: {:.3f}'.
                      format(np.abs(np.dot(np.array(vals[2:]), delta)/np.linalg.norm(delta))))
            if em is not None:
                vals = chord.get_fg(time=em, vel=True)
                delta = np.array(vals[0:2]) - center
                print('    Emersion Radial Velocity: {:.3f}'.
                      format(np.abs(np.dot(np.array(vals[2:]), delta)/np.linalg.norm(delta))))

    @deprecated_alias(log='verbose')  # remove this line in v1.0
    def new_astrometric_position(self, time=None, offset=None, error=None, verbose=True):
        """Calculates the new astrometric position for the object given fitted parameters.

        Parameters:
            time (str,Time): Reference time to calculate the position. If not 
              given, it uses the instant of the occultation Closest Approach.
            offset (list): Offset to apply to the position. If not given, uses 
              the parameters from the fitted ellipse.
              Note:
                  Must be a list of 3 values being [X, Y, 'unit']
                    'unit' must be Angular or Distance unit.
                  If Distance units for X and Y:
                    Ex: [100, -200, 'km'], [0.001, 0.002, 'AU']
                  If Angular units fox X [d*a*cos(dec)] and Y [d*dec]:
                    Ex: [30.6, 20, 'mas'], or [-15, 2, 'arcsec']

            error (list): Error bar of the given offset. If not given, it uses 
              the 1-sigma value of the fitted ellipse.
              Note:
                  Error must be a list of 3 values being [dX, dY, 'unit'], 
                  similar to offset. It does not need to be in the same unit as 
                  offset.
            verbose (bool): If true, it Prints text, else it Returns text.

        """
        from astropy.coordinates import SkyCoord, SkyOffsetFrame

        if time is not None:
            time = Time(time)
        else:
            time = self.tca

        tca_diff = np.absolute(time-self.tca)
        if tca_diff > 1*u.day:
            warnings.warn('The difference between the given time and the closest approach instant is {:.1f} days. '
                          'This position could not have a physical meaning.'.format(tca_diff.jd))

        if offset is not None:
            off_ra = offset[0]*u.Unit(offset[2])
            off_dec = offset[1]*u.Unit(offset[2])
            if off_ra.unit.physical_type == 'length':
                dist = True
            elif off_ra.unit.physical_type == 'angle':
                dist = False
            else:
                raise ValueError('Offset unit must be a distance or angular value.')
        elif hasattr(self, 'fitted_params'):
            off_ra = self.fitted_params['center_f'][0]*u.km
            off_dec = self.fitted_params['center_g'][0]*u.km
            dist = True
        else:
            warnings.warn('No offset given or found. Using 0.0 instead.')
            off_ra = 0.0*u.mas
            off_dec = 0.0*u.mas
            dist = False

        if error is not None:
            e_off_ra = error[0]*u.Unit(error[2])
            e_off_dec = error[1]*u.Unit(error[2])
            if e_off_ra.unit.physical_type == 'length':
                e_dist = True
            elif e_off_ra.unit.physical_type == 'angle':
                e_dist = False
            else:
                raise ValueError('Error unit must be a distance or angular value.')
        elif hasattr(self, 'fitted_params'):
            e_off_ra = self.fitted_params['center_f'][1]*u.km
            e_off_dec = self.fitted_params['center_g'][1]*u.km
            e_dist = True
        else:
            warnings.warn('No error given or found. Using 0.0 instead.')
            e_off_ra = 0.0*u.mas
            e_off_dec = 0.0*u.mas
            e_dist = False

        coord_geo = self.body.ephem.get_position(time)
        distance = coord_geo.distance.to(u.km)
        coord_frame = SkyOffsetFrame(origin=coord_geo)
        if dist:
            off_ra = np.arctan2(off_ra, distance)
            off_dec = np.arctan2(off_dec, distance)
        if e_dist:
            e_off_ra = np.arctan2(e_off_ra, distance)
            e_off_dec = np.arctan2(e_off_dec, distance)
        new_pos = SkyCoord(lon=off_ra, lat=off_dec, frame=coord_frame)
        new_pos = new_pos.icrs

        error_star = self.star.error_at(self.tca)
        error_ra = np.sqrt(error_star[0]**2 + e_off_ra**2)
        error_dec = np.sqrt(error_star[1]**2 + e_off_dec**2)

        out = 'Ephemeris offset (km): X = {:.1f} +/- {:.1f}; Y = {:.1f} +/- {:.1f}\n'.format(
              distance*np.sin(off_ra.to(u.mas)).value, distance*np.sin(e_off_ra.to(u.mas)).value,
              distance*np.sin(off_dec.to(u.mas)).value, distance*np.sin(e_off_dec.to(u.mas)).value)
        out += 'Ephemeris offset (mas): da_cos_dec = {:.3f} +/- {:.3f}; d_dec = {:.3f} +/- {:.3f}\n'.format(
              off_ra.to(u.mas).value, e_off_ra.to(u.mas).value, off_dec.to(u.mas).value, e_off_dec.to(u.mas).value)
        out += '\nAstrometric object position at time {}\n'.format(time.iso)
        out += 'RA = {} +/- {:.3f} mas; DEC = {} +/- {:.3f} mas'.format(
               new_pos.ra.to_string(u.hourangle, precision=7, sep=' '), error_ra.to(u.mas).value,
               new_pos.dec.to_string(u.deg, precision=6, sep=' '), error_dec.to(u.mas).value)

        if verbose:
            print(out)
        else:
            return out

    @deprecated_function(message="Please use chords.plot_chord to have a better control of the plots")
    def plot_chords(self, all_chords=True, positive_color='blue', negative_color='green', error_color='red',
                    ax=None, lw=2):
        """Plots the chords of the occultation.

        Parameters:
            all_chords (bool): if True, it plots all the chords, if False, it 
              sees what was deactivated in self.positions and ignores them.
            positive_color (str): color for the positive chords (Default: blue).
            negative_color (str): color for the negative chords (Default: green).
            error_color (str): color for the error bars of the chords 
              (Default: red).
            ax (maptlotlib.Axes): Axis where to plot chords. (Default: Use 
              matplotlib pool).
            lw (int, float): linewidth of the chords (Default: 2).

        """
        self.chords.plot_chords(segment='positive', only_able=not all_chords, color=positive_color, lw=lw, ax=ax)
        self.chords.plot_chords(segment='error', only_able=not all_chords, color=error_color, lw=lw, ax=ax)
        self.chords.plot_chords(segment='negative', color=negative_color, lw=lw, ax=ax, linestyle='--')

    def get_map_sites(self):
        """Returns Dictionary with sites in the format required by plot_occ_map function.

        Returns:
            sites (dict): Dictionary with the sites in the format required by 
              plot_occ_map function.

        """
        sites = {}
        color = {'positive': 'blue', 'negative': 'red'}
        for name, chord in self.chords.items():
            obs = chord.observer
            sites[name] = [obs.lon.deg, obs.lat.deg, 10, 10, color[chord.status()]]
        return sites

    def plot_occ_map(self, **kwargs):
        """Plots the occultation map.

        Parameters:
            radius: The radius of the shadow. If not given it uses the 
              equatorial radius from the ellipse fit, else it uses the radius 
              obtained from ephem upon instantiating.
            nameimg (str): Change the name of the image saved.
            path (str): Path to a directory where to save map.
            resolution (int): Cartopy feature resolution. 
              "1" means a resolution of "10m",
              "2" a resolution of "50m", and 
              "3" a resolution of "100m" 
              (Default = 2).
            states (bool): True to plot the state division of the countries. 
              The states of some countries will only be shown depending on the 
              resolution.
            zoom (int, float): Zooms in or out of the map.
            centermap_geo (list): Center the map for a given coordinates in 
              longitude and latitude. It must be a list with two numbers 
              (Default=None).
            centermap_delta (list): Displace the center of the map given 
              displacement in X and Y, in km. It must be a list with two 
              numbers (Default=None).
            centerproj (list): Rotates the Earth to show occultation with the 
              center projected at a given longitude and latitude. It must be a 
              list with two numbers.
            labels (bool): Plots text above and below the map with the 
              occultation parameters (Default=True).
            meridians (int): Plots lines representing the meridians for given 
              interval (Default=30 deg).
            parallels (int): Plots lines representing the parallels for given 
              interval (Default=30 deg).
            sites (dict): Plots site positions in map. It must be a python 
              dictionary where the key is the name of the site, and the value 
              is a list with 'longitude', 'latitude', 'delta_x', 'delta_y' and 
              'color'. 'delta_x' and 'delta_y' are displacements, in km, from 
              the point of the site in the map and the name. 'color' is the 
              color of the point. If not given, it calculates from the 
              observations added to Occultation.
            site_name (bool): If True, it prints the name of the sites given, 
              else it plots only the points.
            countries (dict): Plots the names of countries. It must be a python 
              dictionary where the key is the name of the country and the value 
              is a list with longitude and latitude of the lower left part of 
              the text.
            offset (list): applies an offset to the ephemeris, calculating new 
              CA and instant of CA. It is a pair of delta_RA*cosDEC and 
              delta_DEC. If not given it uses the center from ellipse fitted.
            mapstyle (int): Define the color style of the map. 
              '1' is the default black and white scale.
              '2' is a colored map.
            error (int,float): Ephemeris error in mas. It plots a dashed line 
              representing radius + error.
            ercolor (str): Changes the color of the lines of the error bar.
            ring (int,float): It plots a dashed line representing the location 
              of a ring. It is given in km, from the center.
            rncolor (str): Changes the color of ring lines.
            atm (int,float): plots a dashed line representing the location of 
              an atmosphere. It is given in km, from the center.
            atcolor (str): Changes the color of atm lines.
            chord_delta (list): list with distances from center to plot chords.
            chord_geo (2d-list): list with pairs of coordinates to plot chords.
            chcolor (str): color of the line of the chords (Default: grey).
            heights (list): plots a circular dashed line showing the locations 
              where the observer would observe the occultation at a given 
              height above the horizons. 
              Important:
                  This must be a list.
            hcolor (str): Changes the color of the height lines.
            mapsize (list): The size of figure, in cm. It must be a list with 
              two values (Default = [46.0, 38.0]).
            cpoints (int,float): Interval for the small points marking the 
              center of shadow, in seconds (Default=60).
            ptcolor (str): Change the color of the center points.
            alpha (float): The transparency of the night shade, where 0.0 is 
              full transparency and 1.0 is full black (Default = 0.2).
            fmt (str): The format to save the image. It is parsed directly by 
              matplotlib.pyplot (Default = 'png').
            dpi (int): "Dots per inch". It defines the quality of the image
              (Default = 100).
            lncolor (str): Changes the color of the line that represents the 
              limits of the shadow over Earth.
            outcolor (str): Changes the color of the lines that represents the 
              limits of the shadow outside Earth
            nscale (int,float): Arbitrary scale for the size of the name of the site.
            cscale (int,float): Arbitrary scale for the name of the country.
            sscale (int,float): Arbitrary scale for the size of point of the site.
            pscale (int,float): Arbitrary scale for the size of the points that 
              represent the center of the shadow
            arrow (bool): If true, it plots the arrow with the occultation direction.

            Note: 
                Only one of centermap_geo and centermap_delta can be given.

        """
        if 'radius' not in kwargs and hasattr(self, 'fitted_params'):
            r_equa = self.fitted_params['equatorial_radius'][0]
            obla = self.fitted_params['oblateness'][0]
            pos_ang = self.fitted_params['position_angle'][0]
            theta = np.linspace(-np.pi, np.pi, 1800)
            map_pa = self.predict['P/A'][0]
            circle_x = r_equa*np.cos(theta)
            circle_y = r_equa*(1.0-obla)*np.sin(theta)
            ellipse_y = -circle_x*np.sin((pos_ang-map_pa)*u.deg) + circle_y*np.cos((pos_ang-map_pa)*u.deg)
            kwargs['radius'] = ellipse_y.max()
            print('Projected shadow radius = {:.1f} km'.format(kwargs['radius']))
        kwargs['sites'] = kwargs.get('sites', self.get_map_sites())
        if 'offset' not in kwargs and hasattr(self, 'fitted_params'):
            off_ra = self.fitted_params['center_f'][0]*u.km
            off_dec = self.fitted_params['center_g'][0]*u.km
            off_ra = np.arctan2(off_ra, self.dist)
            off_dec = np.arctan2(off_dec, self.dist)
            kwargs['offset'] = [off_ra, off_dec]
        self.predict.plot_occ_map(**kwargs)

    plot_occ_map.__doc__ = PredictionTable.plot_occ_map.__doc__

    def to_log(self, namefile=None):
        """Saves the occultation log to a file.

        Parameters:
            namefile (str): Filename to save the log.

        """
        if namefile is None:
            namefile = 'occ_{}_{}.log'.format(self.body.shortname.replace(' ', '_'), self.tca.isot[:16])
        f = open(namefile, 'w')
        f.write(self.__str__())
        f.close()

    def check_time_shift(self, time_interval=30, time_resolution=0.001, verbose=False, plot=False, use_error=True, delta_plot=100,
                         ignore_chords=None):
        """ Check the needed time offset, so all chords have their center aligned.

        Parameters:
            time_interval (int, float): Time interval to check, default is 
              30 seconds.
            time_resolution (int, float): Time resolution of the search, 
              default is 0.001 seconds.
            verbose (bool): If True, it prints text, default is False.
            plot (bool): If True, it plots figures as a visual aid, default 
              is False.
            use_error (bool): if True, the linear fit considers the time 
              uncertainty, default is True.
            delta_plot (int, float): Value to be added to increase the plot 
              limit, in km. Default is 100.
            ignore_chords (str, list): Names of the chords to be ignored in the 
              linear fit. Default=None.
        Return:
            time_decalage: Dictionary with needed time offset to align the 
              chords, each key is the name of the chord.

        """
        import matplotlib.pyplot as plt
        fm = np.array([])
        gm = np.array([])
        dfm = np.array([])
        dgm = np.array([])
        vfm = np.array([])
        vgm = np.array([])
        chord_name = np.array([])
        ignore_chords = np.array(ignore_chords, ndmin=1)
        use_chords = np.array([], dtype=bool)
        out_dic = {}

        chords = range(len(self.chords))
        for i in chords:
            chord = self.chords[i]
            if chord.status() == 'positive':
                ffm, ggm, vffm, vggm = chord.get_fg(time=chord.lightcurve.time_mean, vel=True)
                df1, dg1, df2, dg2 = chord.path(segment='error')
                dfm = np.append(dfm, np.sqrt(((df1.max() - df1.min())/2)**2 + ((df2.max() - df2.min())/2)**2))
                dgm = np.append(dgm, np.sqrt(((dg1.max() - dg1.min())/2)**2 + ((dg2.max() - dg2.min())/2)**2))
                fm = np.append(fm, ffm)
                gm = np.append(gm, ggm)
                vfm = np.append(vfm, vffm)
                vgm = np.append(vgm, vggm)
                chord_name = np.append(chord_name, chord.name)
                if chord.name in ignore_chords:
                    use_chords = np.append(use_chords, False)
                else:
                    use_chords = np.append(use_chords, True)                
        if len(fm[use_chords]) < 2:
            raise ValueError('The number of fitted chords should be higher than two')        	
        out = self.__linear_fit_error(x=fm[use_chords], y=gm[use_chords], sx=dfm[use_chords], sy=dgm[use_chords],
                                      verbose=verbose, use_error=use_error)
        fm_fit = np.arange(-delta_plot+np.min([fm.min(), gm.min()]), delta_plot+np.max([fm.max(), gm.max()]), 
                           time_resolution*np.absolute(self.vel.value))
        gm_fit = self.__func_line_decalage(out.beta, fm_fit)

        previous_dt = np.array([])
        fm_decalage = np.array([])
        gm_decalage = np.array([])
        time_decalage = np.array([])

        for i, j in enumerate(chord_name):
            previous_dt = np.append(previous_dt, self.chords[j].lightcurve.dt)
            dist_min = np.array([])
            dtt = np.arange(-time_interval, +time_interval, time_resolution)
            for dt in dtt:
                fm_new = fm[i] + dt*vfm[i]
                gm_new = gm[i] + dt*vgm[i]
                dist = np.sqrt((fm_new - fm_fit)**2 + (gm_new - gm_fit)**2)
                dist_min = np.append(dist_min, dist.min())
            print('dt = {:+6.3f} seconds; chord = {}'.format(previous_dt[i] + dtt[dist_min.argmin()], chord_name[i]))
            fm_decalage = np.append(fm_decalage, fm[i] + dtt[dist_min.argmin()]*vfm[i])
            gm_decalage = np.append(gm_decalage, gm[i] + dtt[dist_min.argmin()]*vgm[i])
            time_decalage = np.append(time_decalage, dtt[dist_min.argmin()])
        
        for i in range(len(chord_name)):
            out_dic[chord_name[i]] = time_decalage[i]
        if plot:
            plt.figure(figsize=(5, 5))
            plt.title('Before', fontsize=15)
            self.chords.plot_chords(color='blue')
            self.chords.plot_chords(color='red', segment='error')
            plt.plot(fm[use_chords], gm[use_chords], linestyle='None', marker='o', color='k')
            plt.plot(fm[np.invert(use_chords)], gm[np.invert(use_chords)], linestyle='None', marker='x', color='r')
            plt.plot(fm_fit, gm_fit, 'k-')
            plt.xlim(-delta_plot + np.min([fm.min(), gm.min()]), delta_plot + np.max([fm.max(), gm.max()]))
            plt.ylim(-delta_plot + np.min([fm.min(), gm.min()]), delta_plot + np.max([fm.max(), gm.max()]))
            plt.show()
            for i, j in enumerate(chord_name):
                self.chords[j].lightcurve.dt = previous_dt[i] + time_decalage[i]
            plt.figure(figsize=(5, 5))
            plt.title('After', fontsize=15)
            self.chords.plot_chords(color='blue')
            self.chords.plot_chords(color='red', segment='error')
            plt.plot(fm_decalage[use_chords], gm_decalage[use_chords], linestyle='None', marker='o', color='k')
            plt.plot(fm_decalage[np.invert(use_chords)], gm_decalage[np.invert(use_chords)], linestyle='None', marker='x', color='r')
            plt.plot(fm_fit, gm_fit, 'k-')
            plt.xlim(-delta_plot + np.min([fm.min(), gm.min()]), delta_plot + np.max([fm.max(), gm.max()]))
            plt.ylim(-delta_plot + np.min([fm.min(), gm.min()]), delta_plot + np.max([fm.max(), gm.max()]))
            plt.show()
            for i, j in enumerate(chord_name):
                self.chords[j].lightcurve.dt = previous_dt[i]
        return out_dic

    def to_file(self):
        """Saves the occultation data to a file.

        Three files are saved containing the positions and velocities for the 
        observations. They are for the positive, negative and error bars positions.

        The format of the files are: positions in f and g, velocities in f and 
        g, the Julian Date of the observation, light curve name of the 
        corresponding position.

        """
        pos = []
        neg = []
        err = []
        for name, chord in self.chords.items():
            status = chord.status()
            l_name = name.replace(' ', '_')
            if status == 'positive':
                im = chord.lightcurve.immersion
                ime = chord.lightcurve.immersion_err
                f, g, vf, vg = chord.get_fg(time=im, vel=True)
                f1, g1 = chord.get_fg(time=im-ime*u.s)
                f2, g2 = chord.get_fg(time=im+ime*u.s)
                pos.append([f, g, vf, vg, im.jd, l_name+'_immersion'])
                err.append([f1, g1, vf, vg, (im-ime*u.s).jd, l_name+'_immersion_err-'])
                err.append([f2, g2, vf, vg, (im+ime*u.s).jd, l_name+'_immersion_err+'])

                em = chord.lightcurve.emersion
                eme = chord.lightcurve.emersion_err
                f, g, vf, vg = chord.get_fg(time=em, vel=True)
                f1, g1 = chord.get_fg(time=em-eme*u.s)
                f2, g2 = chord.get_fg(time=em+eme*u.s)
                pos.append([f, g, vf, vg, em.jd, l_name+'_emersion'])
                err.append([f1, g1, vf, vg, (em-eme*u.s).jd, l_name+'_emersion_err-'])
                err.append([f2, g2, vf, vg, (em+eme*u.s).jd, l_name+'_emersion_err+'])

            if status == 'negative':
                ini = chord.lightcurve.initial_time
                f, g, vf, vg = chord.get_fg(time=ini, vel=True)
                neg.append([f, g, vf, vg, ini.jd, l_name+'_start'])

                end = chord.lightcurve.end_time
                f, g, vf, vg = chord.get_fg(time=end, vel=True)
                neg.append([f, g, vf, vg, end.jd, l_name+'_end'])
        if len(pos) > 0:
            f = open('occ_{}_pos.txt'.format(self.body.shortname.replace(' ', '_')), 'w')
            for line in pos:
                f.write('{:10.3f} {:10.3f} {:-6.2f} {:-6.2f} {:16.8f} {}\n'.format(*line))
            f.close()
            f = open('occ_{}_err.txt'.format(self.body.shortname.replace(' ', '_')), 'w')
            for line in err:
                f.write('{:10.3f} {:10.3f} {:-6.2f} {:-6.2f} {:16.8f} {}\n'.format(*line))
            f.close()
        if len(neg) > 0:
            f = open('occ_{}_neg.txt'.format(self.body.shortname.replace(' ', '_')), 'w')
            for line in neg:
                f.write('{:10.3f} {:10.3f} {:-6.2f} {:-6.2f} {:16.8f} {}\n'.format(*line))
            f.close()

    def __str__(self):
        """ String representation of the Occultation class.

        """
        out = ('Stellar occultation of star Gaia-DR2 {} by {}.\n\n'
               'Geocentric Closest Approach: {:.3f}\n'
               'Instant of CA: {}\n'
               'Position Angle: {:.2f}\n'
               'Geocentric shadow velocity: {:.2f}\n'
               'Sun-Geocenter-Target angle:  {:.2f} deg\n'
               'Moon-Geocenter-Target angle: {:.2f} deg\n\n\n'.format(
                   self.star.code, self.body.name, self.ca, self.tca.iso,
                   self.pa, self.vel, self.predict['S-G-T'].data[0],
                   self.predict['M-G-T'].data[0])
               )

        count = {'positive': 0, 'negative': 0, 'visual': 0}
        string = {'positive': '', 'negative': '', 'visual': ''}
        if len(self.chords) > 0:
            for chord in self.chords.values():
                status = chord.status()
                string[status] += chord.__str__() + '\n'
                count[status] += 1

        if len(self.chords) == 0:
            out += 'No observations reported'
        else:
            out += '\n'.join(['{} {} observations'.format(count[k], k) for k in string.keys() if count[k] > 0])

        out += '\n\n'

        out += '#'*79 + '\n{:^79s}\n'.format('STAR') + '#'*79 + '\n'
        out += self.star.__str__() + '\n\n'

        coord = self.star.geocentric(self.tca)
        try:
            error_star = self.star.error_at(self.tca)
        except:
            error_star = [0, 0]*u.mas
        out += 'Geocentric star coordinate at occultation Epoch ({}):\n'.format(self.tca.iso)
        out += 'RA={} +/- {:.4f}, DEC={} +/- {:.4f}\n\n'.format(
            coord.ra.to_string(u.hourangle, sep='hms', precision=5), error_star[0],
            coord.dec.to_string(u.deg, sep='dms', precision=4), error_star[1])

        out += self.body.__str__() + '\n'

        for status in string.keys():
            if count[status] == 0:
                continue
            out += ('#'*79 + '\n{:^79s}\n'.format(status.upper() + ' OBSERVATIONS') + '#'*79)
            out += '\n\n'
            out += string[status]

        if hasattr(self, 'fitted_params'):
            out += '#'*79 + '\n{:^79s}\n'.format('RESULTS') + '#'*79 + '\n\n'
            out += 'Fitted Ellipse:\n'
            out += '\n'.join(['{}: {:.3f} +/- {:.3f}'.format(k, *self.fitted_params[k])
                              for k in self.fitted_params.keys()]) + '\n'
            polar_radius = self.fitted_params['equatorial_radius'][0]*(1.0-self.fitted_params['oblateness'][0])
            equivalent_radius = np.sqrt(self.fitted_params['equatorial_radius'][0]*polar_radius)
            out += 'polar_radius: {:.3f} km \n'.format(polar_radius)
            out += 'equivalent_radius: {:.3f} km \n'.format(equivalent_radius)
            if not np.isnan(self.body.H):
                H_sun = -26.74
                geometric_albedo = (10**(0.4*(H_sun - self.body.H.value))) * ((u.au.to('km')/equivalent_radius)**2)
                out += 'geometric albedo (V): {:.3f} ({:.1%}) \n'.format(geometric_albedo, geometric_albedo)
            else:
                out += 'geometric albedo (V): not calculated, absolute magnitude (H) is unknown \n'
            out += '\nMinimum chi-square: {:.3f}\n'.format(self.chi2_params['chi2_min'])
            out += 'Number of fitted points: {}\n'.format(self.chi2_params['npts'])
            out += 'Number of fitted parameters: {}\n'.format(self.chi2_params['nparam'])
            out += 'Minimum chi-square per degree of freedom: {:.3f}\n'.format(
                self.chi2_params['chi2_min']/(self.chi2_params['npts'] - self.chi2_params['nparam']))
            out += 'Radial dispersion: {:.3f} +/- {:.3f} km\n'.format(
                self.chi2_params['radial_dispersion'].mean(), self.chi2_params['radial_dispersion'].std(ddof=1))
            out += 'Radial error:      {:.3f} +/- {:.3f} km\n'.format(
                self.chi2_params['radial_error'].mean(), self.chi2_params['radial_error'].std(ddof=1))

            out += '\n' + self.new_astrometric_position(verbose=False)

        return out

    def __func_line_decalage(self, p, x):
        """Private function. Returns a linear function, intended for fitting inside the self.check_decalage().
        
        """
        a, b = p
        return a*x + b

    def __linear_fit_error(self, x, y, sx, sy, verbose=False, use_error=True):
        """Private function. Returns a linear fit, intended for fitting inside the self.check_decalage().

        """
        import scipy.odr as odr

        model = odr.Model(self.__func_line_decalage)
        if use_error:
            data = odr.RealData(x=x, y=y, sx=sx, sy=sy)
        else:
            data = odr.RealData(x=x, y=y)
        fit = odr.ODR(data, model, beta0=[0., 1.])
        out = fit.run()
        if verbose:
            print('Linear fit procedure')
            out.pprint()
            print('\n')
        return out
