#!/usr/bin/env python

import sys
import wget
import tarfile
import os
import numpy as np
import glob
import argparse
from argparse import RawDescriptionHelpFormatter

from matplotlib import pyplot as plt
from PIL import Image
from scipy.stats import scoreatpercentile

from urllib.parse import urlencode
from urllib.request import urlretrieve

from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
from astropy.visualization import simple_norm
from astropy import units as u
from astropy.nddata import Cutout2D

from astroquery.mast import Observations

vmin = .5
vmax = 50.

UNWISE_PIXSCALE = 2.75
LEGACY_PIXSCALE = 1

def get_legacy_images(ra,dec,galid='VFID0',pixscale=1,imsize='60',bands='grz',makeplots=False):
    """
    Download legacy image for a particular ra, dec
    
    Inputs:
    * ra
    * dec
    * galid = galaxy id (e.g. VFID0001)
    * imsize = size of cutout in pixels
    * pixscale = pixel scale of cutout in arcsec
      - native is 0.262 for legacy; 
      - 2.75 for wise

    Returns:
    * fits_name
    * jpeg_name
    """
    imsize = int(imsize)    
    rootname = 'cutouts/'+str(galid)+'-legacy-'+str(imsize)
    jpeg_name = rootname+'.jpg'
    fits_name = rootname+'-'+bands+'.fits'


    print('legacy imsize = ',imsize)
    # check if images already exist
    # if not download images
    if not(os.path.exists(jpeg_name)):
        print('retrieving ',jpeg_name)
        url='http://legacysurvey.org/viewer/jpeg-cutout?ra='+str(ra)+'&dec='+str(dec)+'&layer=dr8&size='+str(imsize)+'&pixscale='+str(pixscale)
        urlretrieve(url, jpeg_name)
    else:
        print('previously downloaded ',jpeg_name)
    if not(os.path.exists(fits_name)):
        print('retrieving ',fits_name)
        url='http://legacysurvey.org/viewer/cutout.fits?ra='+str(ra)+'&dec='+str(dec)+'&layer=dr8&size='+str(imsize)+'&pixscale='+str(pixscale)+'&bands='+bands
        urlretrieve(url, fits_name)
    else:
        print('previously downloaded ',fits_name)

    # try to read the data in
    try:
        t,h = fits.getdata(fits_name,header=True)
        
    except IndexError:
        print('problem accessing image')
        print(fits_name)
        url='http://legacysurvey.org/viewer/cutout.fits?ra='+str(ra1)+'&dec='+str(dec1)+'&layer=dr8&size='+str(image_size)+'&pixscale=1.00'
        print(url)
        return None
    
    # write out r-band image
    # nevermind - John M figured out how to use MEF with WCS
    #fits.writeto('r-test.fits',t[1],header=h,overwrite=True)
    if np.mean(t[1]) == 0:
        return None

    if makeplots:
        if jpeg:
            t = Image.open(jpeg_name)
            plt.imshow(t,origin='lower')
        else:
            norm = simple_norm(t[1],stretch='asinh',percent=99.5)            
            plt.imshow(t[1],origin='upper',cmap='gray_r', norm=norm)
    return fits_name, jpeg_name


def get_unwise_image(ra,dec,galid='VFID0',pixscale=2.75,imsize='60',bands='1234',makeplots=False):
    """
    Download unwise image for a particular ra, dec
    
    Inputs:
    * ra
    * dec
    * galid = galaxy id (e.g. VFID0001)
    * imsize = size of cutout in pixels
    * pixscale = pixel scale of cutout in arcsec
      - native is 0.262 for legacy; 
      - 2.75 for wise
    """

    # check if images already exist

    image_names = glob.glob('cutouts/'+galid+'-unwise*img-m.fits')
    if len(image_names) > 3:
        print('unwise images already downloaded')
        if len(image_names) > 4*len(bands):
            multiframe=True
        else:
            multiframe = False
        return image_names,multiframe
    imsize = int(imsize)
    print('wise image size = ',imsize)
    baseurl = 'http://unwise.me/cutout_fits?version=allwise'
    imurl = baseurl +'&ra=%.5f&dec=%.5f&size=%s&bands=%s'%(ra,dec,imsize,bands)
    wisetar = wget.download(imurl)
    tartemp = tarfile.open(wisetar,mode='r:gz') #mode='r:gz'
    wnames = tartemp.getnames()

    print(wnames)
    # check for multiple pointings - means galaxy is split between images
    multiframe = False
    if len(wnames) > 4*len(bands):
        multiframe = True
    
    wmembers = tartemp.getmembers()
    image_names = []
    tartemp.extractall()
    for fname in wnames:
        t = fname.split('-')
        rename = 'cutouts/'+str(galid)+'-'+t[0]+'-'+t[1]+'-'+t[2]+'-'+t[3]+'-'+t[4]
        print('rename = ',rename)
        if os.path.exists(rename): # this should only occur if multiple images are returned from wise
            os.remove(rename)
        os.rename(fname, rename)
        if rename.find('.gz') > -1:
            os.system('gunzip '+rename)
        if fname.find('img') > -1:
            image_names.append(rename)
    os.remove(wisetar)

    if makeplots:
        ##### DISPLAY IMAGE
        im = fits.getdata(rename)
        norm = simple_norm(im, stretch='asinh',percent=99)
        plt.imshow(im, norm=norm)
        plt.show()
    print(image_names)
    print(multiframe)
    return image_names,multiframe

def get_galex_image(ra,dec,imsize):
    """

    get galex image of a galaxy
    
    Input:
    * ra in deg
    * dec in deg
    * imsize in arcsec
    
    Returns:
    * image
    """
    

    # following procedure outlined here:
    # https://astroquery.readthedocs.io/en/latest/mast/mast.html

    # get data products in region near ra,dec
    obs_table = Observations.query_region("%12.8f %12.8f"%(c.ra,c.dec),radius=.1*u.arcmin)
    # create a flag to select galex data
    galexFlag = obs_table['obs_collection'] == 'GALEX'

    # separate out galex data
    data_products = Observations.get_product_list(obs_table[galexFlag])

    # download the observations
    manifest = Observations.download_products(data_products,productType="SCIENCE")

    for m in manifest:
        # choose the first NUV image
        if m['Local Path'].find('nd-int') > -1:
            nuv_path = m['Local Path']
            break
        
    # should be able to construct path from the obs_id in data_products
    # this will let us check if the image is already downloaded
    #
    # I can also save the cutout in a GALEX folder, and
    # look for the image before calling this function
    
    nuv,nuv_header = fits.getdata(nuv_path,header=True)

    # this is a big image, so we need to get a cutout

    nuv_wcs = WCS(nuv_header)
    position = SkyCoord(ra,dec,unit="deg",frame='icrs')
    cutout = Cutout2D(nuv,position,(imsize*u.arcsec,imsize*u.arcsec),wcs=nuv_wcs)

    return cutout
    
def display_image(image,percent=99.5):
    norm = simple_norm(image, stretch='asinh',percent=percent)
    plt.imshow(image, norm=norm,cmap='gray_r')

class cutouts():
    def __init__(self, rimage):
        self.r_name = rimage
        self.wcs = WCS(self.r_name)

        if self.r_name.find('_R') > -1:
            split_string = '_R.fits'

        if self.r_name.find('-R') > -1:
            split_string = '-R.fits'
        elif self.r_name.find('-r') > -1:
            split_string = '_r.fits'
        self.rootname = self.r_name.split(split_string)[0]

    def runall(self):
        self.get_halpha_cutouts()
        self.get_image_size()
        self.get_RADEC()
        self.get_galid()
        self.download_legacy()
        self.load_legacy_images()
        self.download_unwise_images()
        self.load_unwise_images()
        self.get_galex_image()
        self.plotallcutouts()
    def get_halpha_cutouts(self):
        self.r,self.header = fits.getdata(self.r_name,header=True)
        self.ha = fits.getdata(self.rootname+'-Ha.fits')
        self.cs = fits.getdata(self.rootname+'-CS.fits')
    def get_image_size(self):
        # get image size in pixels and arcsec
        self.xsize_pix,self.ysize_pix = self.r.shape
        self.pscale = np.abs(float(self.header['CD1_1']))
        self.xsize_arcsec = self.xsize_pix*self.pscale*3600
        self.ysize_arcsec = self.ysize_pix*self.pscale*3600    
    def get_RADEC(self):
        xcenter = self.xsize_pix/2
        ycenter = self.ysize_pix/2
        self.ra,self.dec = self.wcs.wcs_pix2world(xcenter,ycenter,1)
    def get_galid(self):
        self.galid = self.header['ID']
        
    def download_legacy(self):
        # get legacy grz color and fits
        self.legacy_imsize = self.xsize_arcsec/LEGACY_PIXSCALE
        print('requested legacy imsize = ',self.legacy_imsize)
        self.legacy_filename_g,self.legacy_jpegname = get_legacy_images(self.ra,self.dec,galid=self.galid,imsize=self.legacy_imsize,bands='g')
        self.legacy_filename_r,self.legacy_jpegname = get_legacy_images(self.ra,self.dec,galid=self.galid,imsize=self.legacy_imsize,bands='r')
        self.legacy_filename_z,self.legacy_jpegname = get_legacy_images(self.ra,self.dec,galid=self.galid,imsize=self.legacy_imsize,bands='z')                
        
    def load_legacy_images(self):
        self.legacy_g = fits.getdata(self.legacy_filename_g)
        self.legacy_r = fits.getdata(self.legacy_filename_r)
        self.legacy_z = fits.getdata(self.legacy_filename_z)        
    def download_unwise_images(self,band='1234'):
        '''
        GOAL: Get the unWISE image from the unWISE catalog

        INPUT: ra,dec used to grab unwise image information

        OUTPUT: Name of file to retrieve from

        '''
        self.wise_band = band
        self.wise_imsize = self.xsize_arcsec/UNWISE_PIXSCALE
        print('wise image size = ',self.wise_imsize)
        self.wise_filenames,self.wise_multiframe_flag = \
            get_unwise_image(self.ra,self.dec,galid=self.galid,pixscale='2.75',imsize=self.wise_imsize,bands=self.wise_band)
        
    def load_unwise_images(self):
        if self.wise_multiframe_flag:
            print('WARNING: galaxy falls on multiple unwise images')
        for f in self.wise_filenames:
            if f.find('w1-img') > -1:
                self.w1,self.w1_header = fits.getdata(f,header=True)
            elif f.find('w2-img') > -1:
                self.w2,self.w2_header = fits.getdata(f,header=True)
            elif f.find('w3-img') > -1:
                self.w3,self.w3_header = fits.getdata(f,header=True)
            elif f.find('w4-img') > -1:
                self.w4,self.w4_header = fits.getdata(f,header=True)
    def get_galex_image(self):
        t = self.rootname.split('-')
        self.nuv_image_name = 'galex/'+self.galid+'-'+t[1]+'-nuv.fits'
        if os.path.exists(self.nuv_image_name):
            self.nuv_image = fits.getdata(self.nuv_image_name)
        else:
            cutout = get_galex_image(self.ra,self.dec,self.xsize_arcsec)
            fits.writeto(self.nuv_image_name, cutout.data, overwrite=True)
            self.nuv_image = cutout.data
    def plotcutouts(self,plotsingle=True):
        if plotsingle:
            figu
            re_size=(10,4)
            plt.figure(figsize=figure_size)
            plt.clf()
            plt.subplots_adjust(hspace=0,wspace=0)
        plt.subplot(1,3,1)
        self.plot_ha()
        plt.subplot(1,3,2)
        self.plot_r()
        plt.subplot(1,3,3)
        self.plot_cs()
        plt.show(block=False)        
        plt.savefig(self.rootname+'-cutouts.png')
        plt.savefig(self.rootname+'-cutouts.pdf')
        
    def plotallcutouts(self,plotsingle=True):
        nrow = 3
        ncol = 4

        #Continuum subtracted image
        

        if plotsingle:
            figure_size=(9,7)
            plt.figure(figsize=figure_size)
            plt.clf()
            plt.subplots_adjust(left=.05,right=.95,bottom=.05,top=.9,hspace=.275,wspace=0)
        for i in range(nrow*ncol):
            
            plt.subplot(nrow,ncol,i+1)
            if i == 0:
                self.plot_legacy_jpg()
            elif i < 4:
                # plot each band of legacy
                self.plot_legacy(band=i)
            elif (i > 3) & (i < 8):
                wband = i-3
                self.plot_unwise(band=wband)
            elif i == 8:
                self.plot_ha()
            elif i == 9:
                self.plot_r()
            elif i == 10:
                self.plot_cs()
            elif i == 11:
                self.plot_galex_nuv()
            #if (i%4 != 0):
            if (i > 7) & (i < 11):
                ax = plt.gca()
                mycolor = 'r'
                ax.spines['bottom'].set_color(mycolor)
                ax.spines['top'].set_color(mycolor) 
                ax.spines['right'].set_color(mycolor)
                ax.spines['left'].set_color(mycolor)
            plt.gca().set_yticks(())
            plt.gca().set_xticks(())            
        plt.text(-1.3,3.8,self.rootname,transform=plt.gca().transAxes,fontsize=14,horizontalalignment='center')    
        plt.savefig(self.rootname+'-all-cutouts.png')
        plt.savefig(self.rootname+'-all-cutouts.pdf')        
        
    def plot_legacy_jpg(self):
        # plot jpeg from legacy survey
        t = Image.open(self.legacy_jpegname)        
        plt.imshow(t,origin='lower')
        plt.title(r'$Legacy$')
        pass
    def plot_legacy(self,band=1):
        # plot image from legacy survey
        # band refers to grz (1,2,3)
        if band == 1:
            display_image(self.legacy_g)
            plt.title(r'$Legacy \ g$')            
        elif band == 2:
            display_image(self.legacy_r)
            plt.title(r'$Legacy \ r$')            
        elif band == 3:
            display_image(self.legacy_z)
            plt.title(r'$Legacy \ z$')
        pass
    def plot_unwise(self,band=1):
        # plot image from legacy survey
        # band refers to W1, W2, W3, W4 (1,2,3,4)
        if band == 1:
            display_image(self.w1)
            plt.title(r'$unWISE \ W1$')            
        elif band == 2:
            display_image(self.w2)
            plt.title(r'$unWISE \ W2$')            
        elif band == 3:
            display_image(self.w3)
            plt.title(r'$unWISE \ W3$')
        elif band == 4:
            display_image(self.w4)
            plt.title(r'$unWISE \ W4$')
        pass
    def plot_ha(self):
        #v1,v2=scoreatpercentile(self.ha,[vmin,vmax])#.5,99
        #Halpha plus continuum
        #plt.imshow(self.ha,cmap='gray_r',vmin=v1,vmax=v2,origin='lower')
        display_image(self.ha)
        plt.title(r'$H\alpha + cont$',fontsize=14)
        
    def plot_r(self):
        #R
        #v1,v2=scoreatpercentile(self.r,[vmin,vmax])#.5,99        
        #plt.imshow(self.r,cmap='gray_r',vmin=v1,vmax=v2,origin='lower')
        display_image(self.r)
        plt.title(r'$R$',fontsize=14)
        
    def plot_cs(self):
        #v1,v2=scoreatpercentile(self.cs,[vmin,vmax])
        #plt.imshow(self.cs,origin='lower',cmap='gray_r',vmin=v1,vmax=v2)
        #plt.gca().set_yticks(())
        display_image(self.cs)
        plt.title(r'$H\alpha$',fontsize=14)
        
    def plot_galex_nuv(self):
        display_image(self.nuv_image)
        plt.title(r'$GALEX \ NUV$')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description ='This program subtracts scaled R-band image from Halpha.\n \nTo subtract mosaics:\n~/github/HalphaImaging/uat_subtract_continuum.py --r A1367-h02_R.coadd.fits --ha A1367-h02_ha12.coadd.fits --scale 0.0445 --mosaic \n\nTo subtract cutouts:\n~/github/HalphaImaging/uat_subtract_continuum.py --cluster A1367 --scale 0.044 --id 113364', formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument('--r', dest = 'r', default = None, help = 'R-band image.  This is all you need to provide if images are named: blah_R.fits, blah_CS.fits, blah_Ha.fits')
    parser.add_argument('--ha', dest = 'ha', default = None, help = 'Halpha image.  Use this if you are subtracting mosaic images rather than cutouts.')
    args = parser.parse_args()

    if args.r is None:
        print('you must supply the r-band image name!')
        print('try again')
        sys.exit()
    c = cutouts(args.r)
    c.runall()
    #c.plotcutouts()
