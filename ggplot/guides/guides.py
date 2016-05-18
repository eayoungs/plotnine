from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from copy import deepcopy

import pandas as pd
import numpy as np
from matplotlib.offsetbox import (HPacker, VPacker)

from .guide import guide as guide_class
from ..utils import is_string, is_waive, Registry
from ..utils.exceptions import GgplotError

"""
Terminology
-----------
- A guide is either a legend or colorbar.

- A guide definition (gdef) is an instantiated guide as it
  is used in the process of creating the legend

- The guides class holds all guides that will appear in the
  plot

- A guide box is a fully drawn out guide.
  It is of subclass matplotlib.offsetbox.Offsetbox
"""


class guides(dict):

    def __init__(self, **kwargs):
        aes_names = {'alpha', 'color', 'fill',
                     'linetype', 'shape', 'size'}
        if 'colour' in kwargs:
            kwargs['color'] = kwargs.pop('colour')

        dict.__init__(self, ((ae, kwargs[ae]) for ae in kwargs
                             if ae in aes_names))

    def __radd__(self, gg):
        new_guides = {}
        for k in self:
            new_guides[k] = deepcopy(self[k])
        gg.guides.update(new_guides)
        return gg

    def build(self, plot):
        params = plot.theme.params

        def set_if_none(key, val):
            if params[key] is None:
                params[key] = val

        # by default, guide boxes are vertically aligned
        set_if_none('legend_box', 'vertical')

        # size of key (also used for bar in colorbar guide)
        set_if_none('legend_key_width', params['legend_key_size'])
        set_if_none('legend_key_height', params['legend_key_size'])
        set_if_none('legend_box', 'vertical')

        # by default, direction of each guide depends on
        # the position of the guide_
        set_if_none('legend_position', 'right')
        position = params['legend_position']
        if position in {'top', 'bottom'}:
            set_if_none('legend_direction', 'horizontal')
        else:  # left, right, (default)
            set_if_none('legend_direction', 'vertical')

        # justification of legend boxes
        if position in {'left', 'right'}:
            set_if_none('legend_box_just', 'left')
        else:
            set_if_none('legend_box_just', 'center')

        gdefs = self.train(plot)
        if not gdefs:
            return

        gdefs = self.merge(gdefs)
        gdefs = self.create_geoms(gdefs, plot)

        if not gdefs:
            return

        gboxes = self.draw(gdefs, plot.theme)
        bigbox = self.assemble(gboxes, gdefs, plot.theme)
        return bigbox

    def train(self, plot):
        gdefs = []

        for scale in plot.scales:
            # The guide for aesthetic 'xxx' is stored
            # in plot.guides['xxx']. The priority for
            # the guides depends on how they are created
            # 1. ... + guides(xxx=guide_blah())
            # 2. ... + scale_xxx(guide=guide_blah())
            # 3. default(either guide_legend or guide_colorbar
            #            depending on the scale type)
            output = scale.aesthetics[0]
            guide = self.get(output, scale.guide)

            if guide is None or guide is False:
                continue

            # check the validity of guide.
            # if guide is character, then find the guide object
            guide = self.validate(guide)
            # check the consistency of the guide and scale.
            if (guide.available_aes != 'any' and
                    scale.aesthetics[0] not in guide.available_aes):
                raise GgplotError(
                    "{} cannot be used for {}".format(
                        guide.__class__.__name__, scale.aesthetics))

            # title
            if is_waive(guide.title):
                if scale.name:
                    guide.title = scale.name
                else:
                    guide.title = str(plot.labels[output])

            # direction
            if guide.direction is None:
                guide.direction = plot.theme.params['legend_direction']

            # each guide object trains scale within the object,
            # so Guides (i.e., the container of guides)
            # need not to know about them
            guide = guide.train(scale)

            if guide is not None:
                gdefs.append(guide)

        return gdefs

    def validate(self, guide):
        """
        Validate guide object
        """
        if is_string(guide):
            guide = Registry['guide_{}'.format(guide)]()

        if not isinstance(guide, guide_class):
            raise GgplotError(
                "Unknown guide: {}".format(guide))
        return guide

    def merge(self, gdefs):
        """
        Merge overlapped guides

        e.g
        >>> from ggplot import *
        >>> gg = ggplot(mtcars, aes(y='wt', x='mpg', colour='factor(cyl)'))
        >>> gg = gg + stat_smooth(aes(fill='factor(cyl)'), method='lm')
        >>> gg = gg + geom_point()
        >>> gg

        This would create two guides with the same hash
        """
        # group guide definitions by hash, and
        # reduce each group to a single guide
        # using the guide.merge method
        df = pd.DataFrame({
            'gdef': gdefs,
            'hash': [g.hash for g in gdefs]})
        grouped = df.groupby('hash')
        gdefs = []
        for name, group in grouped:
            # merge
            gdef = group['gdef'].iloc[0]
            for g in group['gdef'].iloc[1:]:
                gdef = gdef.merge(g)
            gdefs.append(gdef)
        return gdefs

    def create_geoms(self, gdefs, plot):
        """
        Add geoms to the guide definitions
        """
        new_gdefs = []
        for gdef in gdefs:
            gdef = gdef.create_geoms(plot)
            if gdef:
                new_gdefs.append(gdef)

        return new_gdefs

    def draw(self, gdefs, theme):
        """
        Draw out each guide definition

        Parameters
        ----------
        gdefs : list of guide_legend|guide_colorbar
            guide definitions
        theme : theme

        Returns
        -------
        out : list of matplotlib.offsetbox.Offsetbox
            A drawing of each legend
        """
        for g in gdefs:
            g._set_defaults(theme)
        return [g.draw(theme) for g in gdefs]

    def assemble(self, gboxes, gdefs, theme):
        """
        Put together all the guide boxes
        """
        # place the guides according to the guide.order
        # 0 do not sort
        # 1-99 sort
        for gdef in gdefs:
            if gdef.order == 0:
                gdef.order = 100
            elif not 0 <= gdef.order <= 99:
                raise GgplotError("'order' for a guide should be",
                                  "between 0 and 99")
        orders = [gdef.order for gdef in gdefs]
        idx = np.argsort(orders)
        gboxes = [gboxes[i] for i in idx]

        # direction when more than legend
        direction = theme.params['legend_box']
        if direction == 'vertical':
            packer = VPacker
        elif direction == 'horizontal':
            packer = HPacker
        else:
            raise GgplotError("'legend_box' should be either",
                              "'vertical' or 'horizontal'")

        align = theme.params['legend_box_just']
        box = packer(children=gboxes, align=align, pad=0, sep=20)
        return box
