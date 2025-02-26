## author: Fernando Paolo
## improve: xin luo, 2022.10.6
## split file into multiple tiles by given meter or degree. if by meter, the coordinates should projected.
##    if by degreen ,the coordinates should be wgs84 (epsg:4326)
## usage: python split_tiles.py pineisland_ATL06_201901.h5 -d 15000 15000 -c lon lat -p 3031 -n 4
##     or python split_tiles.py pineisland_ATL06_201901.h5 -d 0.15 0.15 -c lon lat -p 4326 -n 4

"""
des: split the very-large files into multiple tiles by distance (km)/degree.
"""

import os
import h5py 
import pyproj
import argparse
import numpy as np
from glob import glob
from joblib import Parallel, delayed

# Optimal chunk size of points.
chunks = 100000

def get_args():
    """ Get command-line arguments. """
    parser = argparse.ArgumentParser(
            description='Split geographical data into (overlapping) tiles')
    parser.add_argument(
            'file', metavar='file', type=str, nargs='+',
            help='single or multiple file(s) to split in tiles (HDF5)')
    parser.add_argument(
            '-b', metavar=('w','e','s','n'), dest='bbox', type=float, nargs=4,
            help=('bounding box for geographic region (m/degree)'),
            default=[None,None,None,None],)
    parser.add_argument(
            '-d', metavar=('dxy'), dest='dxy', type=float, nargs=2,
            help=('tile size (m/degree)'),
            default=[None, None], required=True)
    parser.add_argument(
            '-r', metavar=('buffer'), dest='bf', type=float, nargs=1,
            help=("overlap between tiles (m/degree)"),
            default=[0],)
    parser.add_argument(
            '-c', metavar=('lon','lat'), dest='coord_name', type=str, nargs=2,
            help=('name of x/y variables'),
            default=[None, None],)
    parser.add_argument(
            '-p', metavar=('epsg_num'), dest='proj', type=str, nargs=1,
            help=('EPSG proj number (AnIS=3031, GrIS=3413)'),
            default=['3031'],)
    parser.add_argument(
            '-n', metavar=('njobs'), dest='njobs', type=int, nargs=1,
            help="for parallel writing of multiple tiles, optional",
            default=[1],)
    return parser.parse_args()


def print_args(args):
    print('Input arguments:')
    for arg in list(vars(args).items()):
        print(arg)

def coor2coor(srs_from, srs_to, x, y):
    """
    Transform coordinates from srs_from to srs_to
    input:
        srs_from and srs_to are EPSG number (e.g., 4326, 3031)
        x and y are x-coord and y-coord corresponding to srs_from    
    return:
        x-coord and y-coord in srs_to 
    """
    try:
        transformer = pyproj.Transformer.from_crs(srs_from, srs_to,always_xy=True)
        return transformer.transform(x,y)
    except Exception as e:
        print(f"Rrror transforming coordinate:{e}")
        return None,None

def get_xy(ifile, coord_name=['lon', 'lat'], proj='3031'):
    """ Get lon/lat from input file and convert to x/y. """
    lonvar, latvar = coord_name
    try:
        with h5py.File(ifile,'r') as fi:
            lon = fi[lonvar][:]
            lat = fi[latvar][:]
        return coor2coor(4326, proj, lon, lat)
    except KeyError as e:
        print(f"Error :Coordinate variable {e} not found in file {ifile}")
        return None,None
    except Exception as e:
        print(f"Error reading file {ifile}:{e}")
        return None,None


def add_suffix(fname, suffix=''):
    path, ext = os.path.splitext(fname)
    return path + suffix + ext


def get_tile_bboxs(grid_bbox, dx, dy):
    """
    des:    
        Define bbox of tiles given bbox of grid and tile size. 
    """
    xmin, xmax, ymin, ymax = grid_bbox

    # Number of tile edges on each dimension    
    Nns = int(np.abs(ymax - ymin) / dy) + 1   # row
    New = int(np.abs(xmax - xmin) / dx) + 1   # col
    
    # Coord of tile edges for each dimension
    xg = np.linspace(xmin, xmax, New)   
    yg = np.linspace(ymin, ymax, Nns)
    
    # Vector of bbox for each tile   ##NOTE: Nested loop!
    bboxs = [(w,e,s,n) for w, e in zip(xg[:-1], xg[1:]) 
                       for s, n in zip(yg[:-1], yg[1:])]
    del xg, yg
    return bboxs

def get_tile_data(ifile, x, y, bbox, buff=1, proj='3031', tile_num=0):
    """ 
    des:
        Extract data within bbox and save to individual file. 
    args:
        buff: unit is meter. 
    """
    chunks=100000
    print("x 的长度：", len(x))
    print("y 的长度：", len(y))
    xmin, xmax, ymin, ymax = bbox   # given region

    suffix = ('_buff_%g_epsg_%s_tile_%03d' % (buff, proj, tile_num))
    ofile = add_suffix(ifile, suffix)

    with h5py.File(ifile, 'r') as fi:
        vnames = list(fi.keys())
        variables = [fi[key][:] for key in vnames ]

    out = {key: [] for key in vnames}
    npts = 0             # conunt of the written points
    nrow = x.shape[0]

    # read and write in chunks, i: start of each chunk
    for i in range(0, nrow, chunks):
        k = min(i+nrow, nrow)   ## avoid the k exceeds the index range of x.
        x_chunk = x[i:k]
        y_chunk = y[i:k]

        # get the tile indices, 
        idx, = np.where( (x_chunk >= xmin-buff*1e3) & (x_chunk <= xmax+buff*1e3) & 
                         (y_chunk >= ymin-buff*1e3) & (y_chunk <= ymax+buff*1e3) )

        # Leave chunk if outside tile
        if len(idx) == 0:
            continue

        # get chunk of data of the tile
        vars_chunk = [d[i:k] for d in variables]         # -> obtain the points in the chunk
        print("vars_chunk:",vars_chunk)
        vars_chunk_region = [d[idx] for d in vars_chunk]        # -> obtain the points in the given region
        # print("vars_chunk_region",vars_chunk_region)   

        # Save chunk
        for (j, key) in enumerate(vnames):
            # out[key] = out[key] + list(vars_chunk_region[j])
            out[key].extend(vars_chunk_region[j])
        npts += vars_chunk_region[0].shape[0]
    print("最终输出：",out)
    print("总点数:",npts)

    if npts != 0: 
        with h5py.File(ofile, 'w') as out_f:
        # , h5py.File(ifile, 'r') as in_f:
            for key in vnames:
                shape_var = variables[vnames.index(key)].shape
                if len(shape_var) == 1:                        
                    out_f.create_dataset(key, (npts,), dtype='float32')
                    out_f[key][:] = out[key]
                else:
                    out_f.create_dataset(key, (npts, shape_var[1]), dtype='float32')
                    out_f[key][:] = np.array(out[key])
        print(out_f[key][:].shape) 
        print(np.array(out[key]).shape) 
        print(('tile %03d: #points' % tile_num, npts, '...'))

def count_files(ifiles, key='*tile*'):
    saved = []
    for f in ifiles:
        path, ext = os.path.splitext(f)
        # dir_path = os.path.dirname(f)
        # base_name = os.path.basename(path)
        search_pattern = path+key+ext
        matched_files=glob(search_pattern)
        # saved.extend(glob(search_pattern))
        saved.extend(matched_files)
    return len(saved)

if __name__ == '__main__':
    args = get_args()
    ifiles = args.file[:]
    coord_name = args.coord_name[:]
    bbox_ = args.bbox
    bf = args.bf[0]
    dx, dy = args.dxy[0], args.dxy[1]
    proj = args.proj[0]
    njobs = args.njobs[0]

    print_args(args)

    if len(ifiles) == 1:
        ifiles = glob(ifiles[0])

    print('generating list of tasks (files x tiles) ...')

    xys = [get_xy(f, coord_name, proj) for f in ifiles]

    if not bbox_[0]:
        xy = np.vstack(xys)
        xmin, ymin = np.min(xy, axis=0)  # 修正axis为0以确保正确的最小值
        xmax, ymax = np.max(xy, axis=0)  # 修正axis为0以确保正确的最大值
        bbox_ = [xmin, xmax, ymin, ymax]
        
    bboxs = get_tile_bboxs(bbox_, dx, dy)                                   ##[b1,b2]

    fxys = [(f, x, y) for f, (x, y) in zip(ifiles, xys)]                   ##[(f1,x1,y1),(f2,x2,y2)...]
    fxybs = [(f, x, y, b, n+1) for (f, x, y) in fxys for n, b in enumerate(bboxs)]              ##[(f1,x1,y1,b1,1),(f2,x2,y2,b2,2)...]

    print(f'number of files: {len(ifiles)}')
    print(f'number of tiles: {len(bboxs)}')
    print(f'number of tasks: {len(fxybs)}')

    if njobs == 1:
        print('running sequential code ...')
        for f, x, y, b, n in fxybs:
            get_tile_data(f, x, y, b, bf, proj, n)
    else:
        print(f'running parallel code ({njobs} jobs) ...')
        Parallel(n_jobs=njobs, verbose=5)(
            delayed(get_tile_data)(f, x, y, b, bf, proj, n) for f, x, y, b, n in fxybs
        )

    print(f'number of tiles with data: {count_files(ifiles)}')
