#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 Pyresample developers
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
import logging
import math
import os

import numpy as np
import six
import yaml
from pyresample.utils import proj4_str_to_dict

try:
    from xarray import DataArray
except ImportError:
    class DataArray(object):
        """Stand-in for DataArray for holding units information."""

        def __init__(self, data, attrs=None):
            self.attrs = attrs or {}
            self.data = np.array(data)

        def __getitem__(self, item):
            return DataArray(self.data[item], attrs=self.attrs)

        def __getattr__(self, item):
            return self.attrs[item]

        def __len__(self):
            return len(self.data)


class AreaNotFound(KeyError):
    """Exception raised when specified are is no found in file."""
    pass


def load_area(area_file_name, *regions):
    """Load area(s) from area file.

    Parameters
    ----------
    area_file_name : str
        Path to area definition file
    regions : str argument list
        Regions to parse. If no regions are specified all
        regions in the file are returned

    Returns
    -------
    area_defs : AreaDefinition or list
        If one area name is specified a single AreaDefinition object is returned.
        If several area names are specified a list of AreaDefinition objects is returned

    Raises
    ------
    AreaNotFound:
        If a specified area name is not found
    """

    area_list = parse_area_file(area_file_name, *regions)
    if len(area_list) == 1:
        return area_list[0]
    return area_list


def parse_area_file(area_file_name, *regions):
    """Parse area information from area file

    Parameters
    -----------
    area_file_name : str
        Path to area definition file
    regions : str argument list
        Regions to parse. If no regions are specified all
        regions in the file are returned

    Returns
    -------
    area_defs : list
        List of AreaDefinition objects

    Raises
    ------
    AreaNotFound:
        If a specified area is not found
    """

    try:
        return _parse_yaml_area_file(area_file_name, *regions)
    except (yaml.scanner.ScannerError, yaml.parser.ParserError):
        return _parse_legacy_area_file(area_file_name, *regions)


def _read_yaml_area_file_content(area_file_name):
    """Read one or more area files in to a single dict object."""
    from pyresample.utils import recursive_dict_update
    if isinstance(area_file_name, (str, six.text_type)):
        area_file_name = [area_file_name]

    area_dict = {}
    for area_file_obj in area_file_name:
        if (isinstance(area_file_obj, (str, six.text_type)) and
                os.path.isfile(area_file_obj)):
            with open(area_file_obj) as area_file_obj:
                tmp_dict = yaml.safe_load(area_file_obj)
        else:
            tmp_dict = yaml.safe_load(area_file_obj)
        area_dict = recursive_dict_update(area_dict, tmp_dict)

    return area_dict


def _parse_yaml_area_file(area_file_name, *regions):
    """Parse area information from a yaml area file.

    Args:
        area_file_name: filename, file-like object, yaml string, or list of
                        these.

    The result of loading multiple area files is the combination of all
    the files, using the first file as the "base", replacing things after
    that.
    """
    area_dict = _read_yaml_area_file_content(area_file_name)
    area_list = regions or area_dict.keys()
    res = []
    for area_name in area_list:
        params = area_dict.get(area_name)
        if params is None:
            raise AreaNotFound('Area "{0}" not found in file "{1}"'.format(area_name, area_file_name))
        params.setdefault('area_id', area_name)
        # Optional arguments.
        params['shape'] = _capture_subarguments(params, 'shape', ['height', 'width'])
        params['upper_left_extent'] = _capture_subarguments(params, 'upper_left_extent', ['upper_left_extent', 'x', 'y',
                                                                                          'units'])
        params['center'] = _capture_subarguments(params, 'center', ['center', 'x', 'y', 'units'])
        params['area_extent'] = _capture_subarguments(params, 'area_extent', ['area_extent', 'lower_left_xy',
                                                                              'upper_right_xy', 'units'])
        params['resolution'] = _capture_subarguments(params, 'resolution', ['resolution', 'dx', 'dy', 'units'])
        params['radius'] = _capture_subarguments(params, 'radius', ['radius', 'dx', 'dy', 'units'])
        params['rotation'] = _capture_subarguments(params, 'rotation', ['rotation', 'units'])
        res.append(create_area_def(**params))
    return res


def _capture_subarguments(params, arg_name, sub_arg_list):
    """Captures :func:`~pyresample.utils.create_area_def` sub-arguments (i.e. units, height, dx, etc) from a yaml file.

    Example:
        resolution:
          dx: 11
          dy: 22
          units: meters
        # returns DataArray((11, 22), attrs={'units': 'meters})
    """
    # Check if argument is in yaml.
    argument = params.get(arg_name)
    if not isinstance(argument, dict):
        return argument
    argument_keys = argument.keys()
    for sub_arg in argument_keys:
        # Verify that provided sub-arguments are valid.
        if sub_arg not in sub_arg_list:
            raise ValueError('Invalid area definition: {0} is not a valid sub-argument for {1}'.format(sub_arg,
                                                                                                       arg_name))
        elif arg_name in argument_keys:
            # If the arg_name is provided as a sub_arg, then it contains all the data and does not need other sub_args.
            if sub_arg != arg_name and sub_arg != 'units':
                raise ValueError('Invalid area definition: {0} has too many sub-arguments: Both {0} and {1} were '
                                 'specified.'.
                                 format(arg_name, sub_arg))
            # If the arg_name is provided, it's expected that units is also provided.
            elif 'units' not in argument_keys:
                raise ValueError('Invalid area definition: {0} has the sub-argument {0} without units'.format(arg_name))
    units = argument.pop('units', None)
    list_of_values = argument.pop(arg_name, [])
    for sub_arg in sub_arg_list:
        sub_arg_value = argument.get(sub_arg)
        # Don't append units to the argument.
        if sub_arg_value is not None:
            if sub_arg in ('lower_left_xy', 'upper_right_xy') and isinstance(sub_arg_value, list):
                list_of_values.extend(sub_arg_value)
            else:
                list_of_values.append(sub_arg_value)
    # If units are provided, convert to xarray.
    if units is not None:
        return DataArray(list_of_values, attrs={'units': units})
    return list_of_values


def _read_legacy_area_file_lines(area_file_name):
    if isinstance(area_file_name, (str, six.text_type)):
        area_file_name = [area_file_name]

    for area_file_obj in area_file_name:
        if (isinstance(area_file_obj, (str, six.text_type)) and
           not os.path.isfile(area_file_obj)):
            # file content string
            for line in area_file_obj.splitlines():
                yield line
            continue
        elif isinstance(area_file_obj, (str, six.text_type)):
            # filename
            with open(area_file_obj, 'r') as area_file:
                for line in area_file.readlines():
                    yield line


def _parse_legacy_area_file(area_file_name, *regions):
    """Parse area information from a legacy area file."""
    area_file = _read_legacy_area_file_lines(area_file_name)
    area_list = list(regions)
    if not area_list:
        select_all_areas = True
        area_defs = []
    else:
        select_all_areas = False
        area_defs = [None for i in area_list]

    # Extract area from file
    in_area = False
    for line in area_file:
        if not in_area:
            if 'REGION' in line and not line.strip().startswith('#'):
                area_id = line.replace('REGION:', ''). \
                    replace('{', '').strip()
                if area_id in area_list or select_all_areas:
                    in_area = True
                    area_content = ''
        elif '};' in line:
            in_area = False
            try:
                if select_all_areas:
                    area_defs.append(_create_area(area_id, area_content))
                else:
                    area_defs[area_list.index(area_id)] = _create_area(area_id,
                                                                       area_content)
            except KeyError:
                raise ValueError('Invalid area definition: %s, %s' % (area_id, area_content))
        else:
            area_content += line

    # Check if all specified areas were found
    if not select_all_areas:
        for i, area in enumerate(area_defs):
            if area is None:
                raise AreaNotFound('Area "%s" not found in file "%s"' %
                                   (area_list[i], area_file_name))
    return area_defs


def _create_area(area_id, area_content):
    """Parse area configuration"""
    from configobj import ConfigObj
    config_obj = area_content.replace('{', '').replace('};', '')
    config_obj = ConfigObj([line.replace(':', '=', 1)
                            for line in config_obj.splitlines()])
    config = config_obj.dict()
    config['REGION'] = area_id

    try:
        string_types = basestring
    except NameError:
        string_types = str
    if not isinstance(config['NAME'], string_types):
        config['NAME'] = ', '.join(config['NAME'])

    config['XSIZE'] = int(config['XSIZE'])
    config['YSIZE'] = int(config['YSIZE'])
    if 'ROTATION' in config.keys():
        config['ROTATION'] = float(config['ROTATION'])
    else:
        config['ROTATION'] = 0
    config['AREA_EXTENT'][0] = config['AREA_EXTENT'][0].replace('(', '')
    config['AREA_EXTENT'][3] = config['AREA_EXTENT'][3].replace(')', '')

    for i, val in enumerate(config['AREA_EXTENT']):
        config['AREA_EXTENT'][i] = float(val)

    config['PCS_DEF'] = _get_proj4_args(config['PCS_DEF'])
    return create_area_def(config['REGION'], config['PCS_DEF'], description=config['NAME'], proj_id=config['PCS_ID'],
                           shape=(config['YSIZE'], config['XSIZE']), area_extent=config['AREA_EXTENT'],
                           rotation=config['ROTATION'])


def get_area_def(area_id, area_name, proj_id, proj4_args, width, height, area_extent, rotation=0):
    """Construct AreaDefinition object from arguments

    Parameters
    -----------
    area_id : str
        ID of area
    proj_id : str
        ID of projection
    area_name :str
        Description of area
    proj4_args : list, dict, or str
        Proj4 arguments as list of arguments or string
    width : int
        Number of pixel in x dimension
    height : int
        Number of pixel in y dimension
    rotation: float
        Rotation in degrees (negative is cw)
    area_extent : list
        Area extent as a list of ints (LL_x, LL_y, UR_x, UR_y)

    Returns
    -------
    area_def : object
        AreaDefinition object
    """

    proj_dict = _get_proj4_args(proj4_args)
    return create_area_def(area_id, proj_dict, description=area_name, proj_id=proj_id,
                           shape=(height, width), area_extent=area_extent)


def _get_proj4_args(proj4_args):
    """Create dict from proj4 args."""
    from pyresample.utils._proj4 import convert_proj_floats
    if isinstance(proj4_args, (str, six.text_type)):
        proj_config = proj4_str_to_dict(str(proj4_args))
    else:
        from configobj import ConfigObj
        proj_config = ConfigObj(proj4_args)
    return convert_proj_floats(proj_config.items())


def create_area_def(area_id, projection, width=None, height=None, area_extent=None, shape=None, upper_left_extent=None,
                    center=None, resolution=None, radius=None, units=None, **kwargs):
    """Takes data the user knows and tries to make an area definition from what can be found.

    Parameters
    ----------
    area_id : str
        ID of area
    projection : dict or str
        Projection parameters as a proj4_dict or proj4_string
    description : str, optional
        Description/name of area. Defaults to area_id
    proj_id : str, optional
        ID of projection (deprecated)
    units : str, optional
        Units that provided arguments should be interpreted as. This can be
        one of 'deg', 'degrees', 'rad', 'radians', 'meters', 'metres', and any
        parameter supported by the
        `cs2cs -lu <https://proj4.org/apps/cs2cs.html#cmdoption-cs2cs-lu>`_
        command. Units are determined in the following priority:

        1. units expressed with each variable through a DataArray's attrs attribute.
        2. units passed to ``units``
        3. units used in ``projection``
        4. meters

    width : str, optional
        Number of pixels in the x direction
    height : str, optional
        Number of pixels in the y direction
    area_extent : list, optional
        Area extent as a list (lower_left_x, lower_left_y, upper_right_x, upper_right_y)
    shape : list, optional
        Number of pixels in the y and x direction (height, width)
    upper_left_extent : list, optional
        Upper left corner of upper left pixel (x, y)
    center : list, optional
        Center of projection (x, y)
    resolution : list or float, optional
        Size of pixels: (dx, dy)
    radius : list or float, optional
        Length from the center to the edges of the projection (dx, dy)
    rotation: float, optional
        rotation in degrees or radians (negative is cw)
    nprocs : int, optional
        Number of processor cores to be used
    lons : numpy array, optional
        Grid lons
    lats : numpy array, optional
        Grid lats
    optimize_projection:
        Whether the projection parameters have to be optimized for a DynamicAreaDefinition.

    Returns
    -------
    AreaDefinition or DynamicAreaDefinition : AreaDefinition or DynamicAreaDefinition
        If shape and area_extent are found, an AreaDefinition object is returned.
        If only shape or area_extent can be found, a DynamicAreaDefinition object is returned

    Raises
    ------
    ValueError:
        If neither shape nor area_extent could be found

    Notes
    -----
    * ``resolution`` and ``radius`` can be specified with one value if dx == dy
    * If ``resolution`` and ``radius`` are provided as angles, center must be given or findable. In such a case,
      they represent [projection x distance from center[0] to center[0]+dx, projection y distance from center[1] to
      center[1]+dy]
    """
    from pyproj import Proj
    description = kwargs.pop('description', area_id)
    proj_id = kwargs.pop('proj_id', None)

    # Get a proj4_dict from either a proj4_dict or a proj4_string.
    proj_dict = _get_proj_data(projection)
    p = Proj(proj_dict, preserve_units=True)

    # If no units are provided, try to get units used in proj_dict. If still none are provided, use meters.
    if units is None:
        units = proj_dict.get('units', 'm' if not p.is_latlong() else 'degrees')

    # Allow height and width to be provided for more consistency across functions in pyresample.
    if height is not None or width is not None:
        shape = _validate_variable(shape, (height, width), 'shape', ['height', 'width'])

    # Makes sure list-like objects are list-like, have the right shape, and contain only numbers.
    center = _verify_list('center', center, 2)
    radius = _verify_list('radius', radius, 2)
    upper_left_extent = _verify_list('upper_left_extent', upper_left_extent, 2)
    resolution = _verify_list('resolution', resolution, 2)
    shape = _verify_list('shape', shape, 2)
    area_extent = _verify_list('area_extent', area_extent, 4)

    # Converts from lat/lon to projection coordinates (x,y) if not in projection coordinates. Returns tuples.
    center = _convert_units(center, 'center', units, p, proj_dict)
    upper_left_extent = _convert_units(upper_left_extent, 'upper_left_extent', units, p, proj_dict)
    if area_extent is not None:
        # convert area extent, pass as (X, Y)
        area_extent_ll = area_extent[:2]
        area_extent_ur = area_extent[2:]
        area_extent_ll = _convert_units(area_extent_ll, 'area_extent', units, p, proj_dict)
        area_extent_ur = _convert_units(area_extent_ur, 'area_extent', units, p, proj_dict)
        area_extent = area_extent_ll + area_extent_ur
        kwargs['rotation'] = _convert_rotation(kwargs.get('rotation'), units)

    # Fills in missing information to attempt to create an area definition.
    if area_extent is None or shape is None:
        area_extent, shape = _extrapolate_information(area_extent, shape, center, radius, resolution,
                                                      upper_left_extent, units, p, proj_dict)
    return _make_area(area_id, description, proj_id, proj_dict, shape, area_extent, **kwargs)


def _make_area(area_id, description, proj_id, proj_dict, shape, area_extent, **kwargs):
    """Handles the creation of an area definition for create_area_def."""
    from pyresample.geometry import AreaDefinition
    from pyresample.geometry import DynamicAreaDefinition
    # Remove arguments that are only for DynamicAreaDefinition.
    optimize_projection = kwargs.pop('optimize_projection', False)
    # If enough data is provided, create an AreaDefinition. If only shape or area_extent are found, make a
    # DynamicAreaDefinition. If not enough information was provided, raise a ValueError.
    height, width = (None, None)
    if shape is not None:
        height, width = shape
    if None not in (area_extent, shape):
        return AreaDefinition(area_id, description, proj_id, proj_dict, width, height, area_extent, **kwargs)
    elif area_extent is not None or shape is not None:
        return DynamicAreaDefinition(area_id=area_id, description=description, projection=proj_dict, width=width,
                                     height=height, area_extent=area_extent, rotation=kwargs.get('rotation'),
                                     optimize_projection=optimize_projection)
    raise ValueError('Not enough information provided to create an area definition')


def _get_proj_data(projection):
    """Takes a proj4_dict or proj4_string and returns a proj4_dict and a Proj function."""
    if isinstance(projection, str):
        proj_dict = proj4_str_to_dict(projection)
    elif isinstance(projection, dict):
        proj_dict = projection
    else:
        raise TypeError('Wrong type for projection: {0}. Expected dict or string.'.format(type(projection)))
    return proj_dict


def _convert_rotation(rotation, units):
    """Convert rotation to degrees."""
    if rotation is None:
        return None
    if isinstance(rotation, DataArray):
        if hasattr(rotation, 'units'):
            units = rotation.units
        if units not in ['deg', 'degrees', 'rad',  'radians']:
            raise ValueError('units provided to rotation are incorrect: {0}'.format(units))
        rotation = rotation.data
    if units in ['rad',  'radians']:
        rotation *= 180 / math.pi
    return rotation


def _sign(num):
    """Return the sign of the number provided.

    Returns:
        1 if number is greater than 0, -1 otherwise

    """
    return -1 if num < 0 else 1


def _round_poles(center, units, p):
    """Round center to the nearest pole if it is extremely close to said pole.

    Used to work around floating point precision issues .

    """
    # For a laea projection, this allows for an error of 11 meters around the pole.
    error = .0001
    if 'deg' in units:
        if abs(abs(center[1]) - 90) < error:
            center = (center[0], _sign(center[1]) * 90)
    elif 'rad' in units:
        if abs(abs(center[1]) - math.pi / 2) < error * math.pi / 180:
            center = (center[0], _sign(center[1]) * math.pi / 2)
    else:
        center = p(*center, inverse=True, errcheck=True)
        if abs(abs(center[1]) - 90) < error:
            center = (center[0], _sign(center[1]) * 90)
        center = p(*center, errcheck=True)
    return center


def _distance_from_center_forward(var, center, p, is_radians):
    """Convert distances in radians or degrees to projection units."""
    # Interprets radius and resolution as distances between latitudes/longitudes.
    # Since the distance between longitudes and latitudes is not constant in
    # most projections, there must be reference point to start from.
    if center is None:
        raise ValueError('center must be given to convert radius or resolution from an angle to meters')

    center_as_angle = p(*center, radians=is_radians, inverse=True, errcheck=True)
    pole = 90
    if is_radians:
        pole = math.pi / 2
    # If on a pole, use northern/southern latitude for both height and width.
    if abs(abs(center_as_angle[1]) - pole) < 1e-8:
        direction_of_poles = _sign(center_as_angle[1])
        var = (center[1] - p(0, center_as_angle[1] - direction_of_poles * abs(var[0]),
                             radians=is_radians, errcheck=True)[1],
               center[1] - p(0, center_as_angle[1] - direction_of_poles * abs(var[1]),
                             radians=is_radians, errcheck=True)[1])
    # Uses southern latitude and western longitude if radius is positive. Uses northern latitude and
    # eastern longitude if radius is negative.
    else:
        var = (center[0] - p(center_as_angle[0] - var[0], center_as_angle[1], radians=is_radians, errcheck=True)[0],
               center[1] - p(center_as_angle[0], center_as_angle[1] - var[1], radians=is_radians, errcheck=True)[1])
    return var


def _convert_units(var, name, units, p, proj_dict, inverse=False, center=None):
    """Converts units from lon/lat to projection coordinates (meters).

    If `inverse` it True then the inverse calculation is done.

    """
    from pyproj import transform, Proj
    if var is None:
        return None
    if isinstance(var, DataArray):
        units = var.units
        var = tuple(var.data.tolist())
    if p.is_latlong() and ('m' == units or 'meters' == units or 'metres' == units):
        raise ValueError('latlon/latlong projection cannot take meters as units: {0}'.format(name))
    # Check if units are an angle.
    is_angle = ('deg' == units or 'rad' == units or 'degrees' == units or 'radians' == units)
    is_radians = 'rad' in units
    if ('deg' in units or 'rad' in units) and not is_angle:
        logging.warning('units provided to {0} are incorrect: {1}'.format(name, units))
    # Convert from var projection units to projection units given by projection from user.
    if not is_angle:
        if units == 'meters' or units == 'metres':
            units = 'm'
        if proj_dict.get('units', 'm') != units:
            tmp_proj_dict = proj_dict.copy()
            tmp_proj_dict['units'] = units
            var = transform(Proj(tmp_proj_dict, preserve_units=True), p, *var)
    if name == 'center':
        var = _round_poles(var, units, p)
    # Return either degrees or meters depending on if the inverse is true or not.
    # Don't convert if inverse is True: Want degrees/radians.
    # Converts list-like from degrees/radians to meters.
    if is_angle and not inverse:
        if name in ('radius', 'resolution'):
            var = _distance_from_center_forward(var, center, p, is_radians)
        else:
            var = p(*var, radians=is_radians, errcheck=True)
    # Don't convert if inverse is False: Want meters.
    elif not is_angle and inverse:
        # Converts list-like from meters to degrees.
        var = p(*var, inverse=True, errcheck=True)
    if name in ['radius', 'resolution']:
        var = (abs(var[0]), abs(var[1]))
    return var


def _round_shape(shape, radius=None, resolution=None):
    """Make sure shape is an integer.

    Rounds down if shape is less than .01 above nearest whole number to
    handle floating point precision issues. Otherwise the number is round
    up.

    """
    # Used for area definition to prevent indexing None.
    if shape is None:
        return None
    incorrect_shape = False
    height, width = shape
    if abs(width - round(width)) > 1e-8:
        incorrect_shape = True
        if width - math.floor(width) >= .01:
            width = math.ceil(width)
    width = int(round(width))
    if abs(height - round(height)) > 1e-8:
        incorrect_shape = True
        if height - math.floor(height) >= .01:
            height = math.ceil(height)
    height = int(round(height))
    if incorrect_shape:
        if radius is not None and resolution is not None:
            new_resolution = (2 * radius[0] / width, 2 * radius[1] / height)
            logging.warning('shape found from radius and resolution does not contain only '
                            'integers: {0}\nRounding shape to {1} and resolution from {2} meters to '
                            '{3} meters'.format(shape, (height, width), resolution, new_resolution))
        else:
            logging.warning('shape provided does not contain only integers: {0}\n'
                            'Rounding shape to {1}'.format(shape, (height, width)))
    return height, width


def _validate_variable(var, new_var, var_name, input_list):
    """Makes sure data given by the user does not conflict with itself.

    If a variable that was given by the user contradicts other data provided, an exception is raised.
    Example: upper_left_extent is (-10, 10), but area_extent is (-20, -20, 20, 20).

    """
    if var is not None and not np.allclose(np.array(var, dtype=float), np.array(new_var, dtype=float), equal_nan=True):
        raise ValueError('CONFLICTING DATA: {0} given does not match {0} found from {1}'.format(
            var_name, ', '.join(input_list)) + ':\ngiven: {0}\nvs\nfound: {1}'.format(var, new_var, var_name,
                                                                                      input_list))
    return new_var


def _extrapolate_information(area_extent, shape, center, radius, resolution, upper_left_extent, units, p, proj_dict):
    """Attempts to find shape and area_extent based on data provided.

    Parameters are used in a specific order to determine area_extent and shape.
    The area_extent and shape are later used to create an `AreaDefinition`.
    Providing some parameters may have no effect if other parameters could be
    to used determine area_extent and shape. The order of the parameters used
    is:

    1. area_extent
    2. upper_left_extent and center
    3. radius and resolution
    4. resolution and shape
    5. radius and center
    6. upper_left_extent and radius

    """
    # Input unaffected by data below: When area extent is calculated, it's either with
    # shape (giving you an area definition) or with center/radius/upper_left_extent (which this produces).
    # Yet output (center/radius/upper_left_extent) is essential for data below.
    if area_extent is not None:
        # Function 1-A
        new_center = ((area_extent[2] + area_extent[0]) / 2, (area_extent[3] + area_extent[1]) / 2)
        center = _validate_variable(center, new_center, 'center', ['area_extent'])
        # If radius is given in an angle without center it will raise an exception, and to verify, it must be in meters.
        radius = _convert_units(radius, 'radius', units, p, proj_dict, center=center)
        new_radius = ((area_extent[2] - area_extent[0]) / 2, (area_extent[3] - area_extent[1]) / 2)
        radius = _validate_variable(radius, new_radius, 'radius', ['area_extent'])
        new_upper_left_extent = (area_extent[0], area_extent[3])
        upper_left_extent = _validate_variable(
            upper_left_extent, new_upper_left_extent, 'upper_left_extent', ['area_extent'])
    # Output used below, but nowhere else is upper_left_extent made. Thus it should go as early as possible.
    elif None not in (upper_left_extent, center):
        # Function 1-B
        radius = _convert_units(radius, 'radius', units, p, proj_dict, center=center)
        new_radius = (center[0] - upper_left_extent[0], upper_left_extent[1] - center[1])
        radius = _validate_variable(radius, new_radius, 'radius', ['upper_left_extent', 'center'])
    else:
        radius = _convert_units(radius, 'radius', units, p, proj_dict, center=center)
    # Convert resolution to meters if given as an angle. If center is not found, an exception is raised.
    resolution = _convert_units(resolution, 'resolution', units, p, proj_dict, center=center)
    # Inputs unaffected by data below: area_extent is not an input. However, output is used below.
    if radius is not None and resolution is not None:
        # Function 2-A
        new_shape = _round_shape((2 * radius[1] / resolution[1], 2 * radius[0] / resolution[0]), radius=radius,
                                 resolution=resolution)
        shape = _validate_variable(shape, new_shape, 'shape', ['radius', 'resolution'])
    elif resolution is not None and shape is not None:
        # Function 2-B
        new_radius = (resolution[0] * shape[1] / 2, resolution[1] * shape[0] / 2)
        radius = _validate_variable(radius, new_radius, 'radius', ['shape', 'resolution'])
    # Input determined from above functions, but output does not affect above functions: area_extent can be
    # used to find center/upper_left_extent which are used to find each other, which is redundant.
    if center is not None and radius is not None:
        # Function 1-C
        new_area_extent = (center[0] - radius[0], center[1] - radius[1], center[0] + radius[0], center[1] + radius[1])
        area_extent = _validate_variable(area_extent, new_area_extent, 'area_extent', ['center', 'radius'])
    elif upper_left_extent is not None and radius is not None:
        # Function 1-D
        new_area_extent = (
            upper_left_extent[0], upper_left_extent[1] - 2 * radius[1], upper_left_extent[0] + 2 * radius[0],
            upper_left_extent[1])
        area_extent = _validate_variable(area_extent, new_area_extent, 'area_extent', ['upper_left_extent', 'radius'])
    return area_extent, shape


def _format_list(var, name):
    """Used to let resolution and radius be single numbers if their elements are equal.

    Also makes sure that data is list-like and contains only numbers.
    """
    # Single-number format.
    if not isinstance(var, (list, tuple)) and name in ('resolution', 'radius'):
        var = (float(var), float(var))
    elif name == 'shape':
        var = _round_shape(var)
    else:
        var = tuple(float(num) for num in var)
    return var


def _verify_list(name, var, length):
    """Checks that list-like variables are list-like, shapes are accurate, and values are numbers."""
    # Make list-like data into tuples (or leave as xarrays). If not list-like, throw a ValueError unless it is None.
    if var is None:
        return None
    # Verify that list is made of numbers and is list-like.
    try:
        if 'units' in getattr(var, 'attrs', {}) and name != 'shape':
            # For len(var) to work, DataArray must contain a list, not a tuple
            var = DataArray(list(_format_list(var.data.tolist(), name)), attrs=var.attrs)
        elif isinstance(var, DataArray):
            if name == 'shape':
                logging.warning("{0} is unitless, but was passed as a DataArray".format(name, var.attrs))
            else:
                logging.warning("{0} is a DataArray but does not have the attribute 'units',"
                                "but instead has attribute(s): {1}".format(name, var.attrs))
            var = _format_list(var.data.tolist(), name)
        else:
            var = _format_list(var, name)
    except TypeError:
        raise ValueError('{0} is not list-like:\n{1}'.format(name, var))
    except ValueError:
        raise ValueError('{0} is not composed purely of numbers:\n{1}'.format(name, var))
    # Confirm correct shape
    if len(var) != length:
        raise ValueError('{0} should have length {1}, but instead has length {2}:\n{3}'.format(name, length,
                                                                                               len(var), var))
    return var


def convert_def_to_yaml(def_area_file, yaml_area_file):
    """Convert a legacy area def file to the yaml counter partself.

    *yaml_area_file* will be overwritten by the operation.
    """
    areas = _parse_legacy_area_file(def_area_file)
    with open(yaml_area_file, 'w') as yaml_file:
        for area in areas:
            yaml_file.write(area.create_areas_def())
