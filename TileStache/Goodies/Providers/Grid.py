""" Grid rendering for TileStache.

UTM provider found here draws gridlines in tiles, in transparent images suitable
for use as map overlays.

Example TileStache provider configuration:

"grid":
{
    "provider": {"class": "TileStache.Goodies.Providers.Grid.UTM",
                 "kwargs": {"display": "MGRS", "spacing": 200, "tick": 10}}
}
"""

from math import log as _log, pow as _pow, hypot as _hypot, ceil as _ceil

import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont

import TileStache

try:
    from pyproj import Proj
except ImportError:
    # well I guess we can't do any more things now.
    pass

def lat2hemi(lat):
    """ Convert latitude to single-letter hemisphere, "N" or "S".
    """
    return lat >= 0 and 'N' or 'S'

def lon2zone(lon):
    """ Convert longitude to numeric UTM zone, 1-60.
    """
    zone = int(round(lon / 6. + 30.5))
    return ((zone - 1) % 60) + 1

def lat2zone(lat):
    """ Convert longitude to single-letter UTM zone.
    """
    zone = int(round(lat / 8. + 9.5))
    return 'CDEFGHJKLMNPQRSTUVWX'[zone]

def lonlat2grid(lon, lat):
    """ Convert lat/lon pair to alphanumeric UTM zone.
    """
    return '%d%s' % (lon2zone(lon), lat2zone(lat))

def utm2mgrs(e, n, grid, zeros=0):
    """ Convert UTM easting/northing pair and grid zone
        to MGRS-style grid reference, e.g. "18Q YF 80 52".
        
        Adapted from http://haiticrisismap.org/js/usng2.js
    """
    square_set = int(grid[:-1]) % 6
    
    ew_idx = int(e / 100000) - 1            # should be [100000, 9000000]
    ns_idx = int((n % 2000000) / 100000)    # should [0, 10000000) => [0, 2000000)
    
    ns_letters_135 = 'ABCDEFGHJKLMNPQRSTUV'
    ns_letters_246 = 'FGHJKLMNPQRSTUVABCDE'
    
    ew_letters_14 = 'ABCDEFGH'
    ew_letters_25 = 'JKLMNPQR'
    ew_letters_36 = 'STUVWXYZ'

    if square_set == 1:
        square = ew_letters_14[ew_idx] + ns_letters_135[ns_idx]

    elif square_set == 2:
        square = ew_letters_25[ew_idx] + ns_letters_246[ns_idx]

    elif square_set == 3:
        square = ew_letters_36[ew_idx] + ns_letters_135[ns_idx]

    elif square_set == 4:
        square = ew_letters_14[ew_idx] + ns_letters_246[ns_idx]

    elif square_set == 5:
        square = ew_letters_25[ew_idx] + ns_letters_135[ns_idx]

    else:
        square = ew_letters_36[ew_idx] + ns_letters_246[ns_idx]

    easting = '%05d' % (e % 100000)
    northing = '%05d' % (n % 100000)
    
    return ' '.join( [grid, square, easting[:-zeros], northing[:-zeros]] )

def transform(w, h, xmin, ymax, xmax, ymin):
    """
    """
    xspan, yspan = (xmax - xmin), (ymax - ymin)

    xm = w / xspan
    ym = h / yspan
    
    xb = w - xm * xmax
    yb = h - ym * ymax
    
    return lambda x, y: (int(xm * x + xb), int(ym * y + yb))

class UTM:
    """ UTM Grid provider, renders transparent gridlines.
    
        Example configuration:
    
        "grid":
        {
            "provider": {"class": "TileStache.Goodies.Providers.Grid.UTM",
                         "kwargs": {"display": "MGRS", "spacing": 200, "tick": 10}}
        }
    
        Additional arguments:
        
        - display (optional, default: "UTM")
            Label display style. UTM: "18Q 0780 2052", MGRS: "18Q YF 80 52".
        - spacing (optional, default: 128)
            Minimum number of pixels between grid lines.
        - tick (optional, default 8)
            Pixel length of 1/10 grid tick marks.
    """
    
    metatileOK = True
    
    def __init__(self, layer, display='UTM', spacing=128, tick=8):
        self.display = display.lower()
        self.spacing = int(spacing)
        self.tick = int(tick)

    def renderArea(self, width_, height_, srs, xmin_, ymin_, xmax_, ymax_):
        """
        """
        merc = Proj(srs)
        
        # use the center to figure out our UTM zone
        lon, lat = merc((xmin_ + xmax_)/2, (ymin_ + ymax_)/2, inverse=True)
        zone = lon2zone(lon)
        hemi = lat2hemi(lat)

        utm = Proj(proj='utm', zone=zone, datum='WGS84')
        
        # get to UTM coords
        (minlon, minlat), (maxlon, maxlat) = merc(xmin_, ymin_, inverse=1), merc(xmax_, ymax_, inverse=1)
        (xmin, ymin), (xmax, ymax) = utm(minlon, minlat), utm(maxlon, maxlat)

        # figure out how widely-spaced they should be
        pixels = _hypot(width_, height_)            # number of pixels across the image
        units = _hypot(xmax - xmin, ymax - ymin)    # number of UTM units across the image
        
        tick = self.tick * units/pixels             # desired tick length in UTM units
        
        count = pixels / self.spacing               # approximate number of lines across the image
        bound = units / count                       # too-precise step between lines in UTM units
        zeros = int(_ceil(_log(bound) / _log(10)))  # this value gets used again to format numbers
        step = int(_pow(10, zeros))                 # a step that falls right on the 10^n
        
        # and the outer UTM bounds
        xbot, xtop = int(xmin - xmin % step), int(xmax - xmax % step) + 2 * step
        ybot, ytop = int(ymin - ymin % step), int(ymax - xmax % step) + 2 * step
    
        # start doing things in pixels
        img = PIL.Image.new('RGBA', (width_, height_), (0xEE, 0xEE, 0xEE, 0x00))
        draw = PIL.ImageDraw.ImageDraw(img)
        font = PIL.ImageFont.truetype('DejaVuSansMono.ttf', 14)
        xform = transform(width_, height_, xmin_, ymax_, xmax_, ymin_)
        
        lines = []
        labels = []
        
        for col in range(xbot, xtop, step):
            # set up the verticals
            utms = [(col, y) for y in range(ybot, ytop, step/10)]
            mercs = [merc(*utm(x, y, inverse=1)) for (x, y) in utms]
            lines.append( [xform(x, y) for (x, y) in mercs] )
            
            # and the tick marks
            for row in range(ybot, ytop, step/10):
                mercs = [merc(*utm(x, y, inverse=1)) for (x, y) in ((col, row), (col - tick, row))]
                lines.append( [xform(x, y) for (x, y) in mercs] )
        
        for row in range(ybot, ytop, step):
            # set up the horizontals
            utms = [(x, row) for x in range(xbot, xtop, step/10)]
            mercs = [merc(*utm(x, y, inverse=1)) for (x, y) in utms]
            lines.append( [xform(x, y) for (x, y) in mercs] )
            
            # and the tick marks
            for col in range(xbot, xtop, step/10):
                mercs = [merc(*utm(x, y, inverse=1)) for (x, y) in ((col, row), (col, row - tick))]
                lines.append( [xform(x, y) for (x, y) in mercs] )

        # set up the intersection labels
        for x in range(xbot, xtop, step):
            for y in range(ybot, ytop, step):
                lon, lat = utm(x, y, inverse=1)
                grid = lonlat2grid(lon, lat)
                point = xform(*merc(lon, lat))
                
                if self.display == 'utm':
                    e = ('%07d' % x)[:-zeros]
                    n = ('%07d' % y)[:-zeros]
                    text = ' '.join( [grid, e, n] )

                elif self.display == 'mgrs':
                    e, n = Proj(proj='utm', zone=lon2zone(lon), datum='WGS84')(lon, lat)
                    text = utm2mgrs(round(e), round(n), grid, zeros)
                
                labels.append( (point, text) )

        # do the drawing bits
        for ((x, y), text) in labels:
            x, y = x + 2, y - 18
            w, h = font.getsize(text)
            draw.rectangle((x - 2, y, x + w + 2, y + h), fill=(0xFF, 0xFF, 0xFF, 0x99))

        for line in lines:
            draw.line(line, fill=(0xFF, 0xFF, 0xFF))

        for line in lines:
            draw.line([(x-1, y-1) for (x, y) in line], fill=(0x00, 0x00, 0x00))

        for ((x, y), text) in labels:
            x, y = x + 2, y - 18
            draw.text((x, y), text, fill=(0x00, 0x00, 0x00), font=font)

        return img