#!/usr/bin/env python

'''
USAGE:

from within ipython:
%run ~/github/HalphaImaging/getzp.py --image pointing031-r.coadd.fits --instrument i --filter r

The y intercept is -1*ZP

To print the value in ipython, type:

-1*zp.bestc[1]


UPDATES:
* implemented scipy.optimize.curve_fit in getzp.py to 
    * keep slope fixed at 1
    * get an estimate of error in ZP (sqrt(covariance))
* program now prints ZP and error at the end

NOTES:

2019-06-12
* making sure saturated stars are ignored
- coadd produced by swarp is in ADU/exptime
- added argument nexptime that allows user to toggle between images in ADU vs ADU/s.  If image is in ADU/s, then I grab the exptime from the image header and change SATUR_LEVEL to 40000./exptime


Apertures:
- by default, we are using aperture magnitudes, aperture 5 is default, which is
REFERENCES:

Pan-STARRS
https://michaelmommert.wordpress.com/2017/02/13/accessing-the-gaia-and-pan-starrs-catalogs-using-python/

https://panstarrs.stsci.edu/


GAIA
https://gea.esac.esa.int/archive/documentation/GDR1/Data_processing/chap_cu5phot/sec_phot_calibr.html

https://www.cosmos.esa.int/web/gaia/dr2-known-issues


OLD SDSS QUERY
from astroquery.sdss import SDSS


query = 'SELECT TOP 10 ra, dec, u,g,r,i,z, flags_r FROM Star WHERE (clean = 1) AND ra BETWEEN 180 and 181 AND dec BETWEEN -0.5 and 0.5 AND ((flags_r & 0x10000000) != 0) AND ((flags_r & 0x8100000c00a4) = 0) AND (((flags_r & 0x400000000000) = 0) or (psfmagerr_r <= 0.2)) AND (((flags_r & 0x100000000000) = 0) or (flags_r & 0x1000) = 0)'

t = SDSS.query_sql(query, data_release=14)
'''

import argparse
import os
import numpy as np
import sys
from matplotlib import pyplot as plt
import matplotlib.patches as patches
import astropy.units as u
import astropy.coordinates as coord
from astropy.coordinates import SkyCoord
from astropy.io import fits
from scipy.optimize import curve_fit
from astroquery.vizier import Vizier

# function for fitting ZP equation
# this one forces slope = 1
zpfunc = lambda x, zp: x + zp
# this function allows the slope to vary
zpfuncwithslope = lambda x, m, zp: m*x + zp

pixelscale = 0.43 # arcsec per pixel

def panstarrs_query(ra_deg, dec_deg, rad_deg, maxmag=20,
                    maxsources=10000):
    """
    FOUND THIS ON THE WEB 
    https://michaelmommert.wordpress.com/2017/02/13/accessing-the-gaia-and-pan-starrs-catalogs-using-python/

    
    Query PanSTARRS @ VizieR using astroquery.vizier
    :param ra_deg: RA in degrees
    :param dec_deg: Declination in degrees
    :param rad_deg: field radius in degrees
    :param maxmag: upper limit G magnitude (optional)
    :param maxsources: maximum number of sources
    :return: astropy.table object
    """
    pan_columns =['objID', 'RAJ2000', 'DEJ2000','e_RAJ2000', 'e_DEJ2000', 'f_objID', 'Qual','gmag', 'e_gmag','rmag', 'e_rmag','imag', 'e_imag','zmag', 'e_zmag','ymag', 'e_ymag']
    #print(pan_columns)
    vquery = Vizier(columns=pan_columns,column_filters={"gmag":("<%f" % maxmag)},row_limit=maxsources)

    field = coord.SkyCoord(ra=ra_deg, dec=dec_deg,
                           unit=(u.deg, u.deg),
                           frame='icrs')
    return vquery.query_region(field,
                               width=("%fd" % rad_deg),
                               catalog="II/349/ps1")[0]


class getzp():
    def __init__(self, image, instrument='h', filter='r', astromatic_dir = '~/github/HalphaImaging/astromatic/',norm_exptime = True,nsigma = 2., useri = False, naper = 5, mag=0):

        self.image = image
        self.astrodir = astromatic_dir
        self.instrument = instrument
        self.filter = filter
        # if image is in ADU rather than ADU/s, divide image by exptime before running sextractor
        if not(norm_exptime):
            im, header = fits.getdata(self.image,header=True)
            exptime = header['EXPTIME']
            norm_im = im/float(exptime)
            fits.writeto('n'+self.image, norm_im, header, overwrite=True)
            self.image = 'n'+self.image
        print('output image = ',self.image)
        self.nsigma = nsigma
        self.useri = useri
        self.naper = naper
        self.mag = mag
    def getzp(self):
        print('STATUS: running se')        
        self.runse()
        print('STATUS: getting panstarrs')
        self.get_panstarrs() 
        print('STATUS: matching se cat to panstarrs')       
        self.match_coords()
        print('STATUS: fitting zeropoint')        
        self.fitzp()
        print('STATUS: udating header')        
        self.update_header()
    def runse(self):
        #####
        # Run Source Extractor on image to measure magnitudes
        ####

        os.system('cp ' +self.astrodir + '/default.* .')
        t = self.image.split('.fits')
        froot = t[0]
        if self.instrument == 'h':
            defaultcat = 'default.sex.HDI'
        elif self.instrument == 'i':
            defaultcat = 'default.sex.HDI'
            self.keepsection=[1000,5000,0,4000]
        elif self.instrument == 'm':
            defaultcat = 'default.sex.HDI'
        header = fits.getheader(self.image)
        expt = header['EXPTIME']
        ADUlimit = 4000000./float(expt)
        print('saturation limit in ADU/s {:.1f}'.format(ADUlimit))
        if args.fwhm is None:
            t = 'sex ' + self.image + ' -c '+defaultcat+' -CATALOG_NAME ' + froot + '.cat -MAG_ZEROPOINT 0 -SATUR_LEVEL '+str(ADUlimit)
            #t = 'sex ' + self.image + ' -c '+defaultcat+' -CATALOG_NAME ' + froot + '.cat -MAG_ZEROPOINT 0 -SATUR_LEVEL '
            print('running SE first time to get estimate of FWHM')
            print(t)
            os.system(t)

            # clean up SE files
            # skipping for now in case the following command accidentally deletes user files
            # os.system('rm default.* .')


            ###################################
            # Read in Source Extractor catalog
            ###################################
            print('reading in SE catalog from first pass')
            secat_filename = froot+'.cat'
            self.secat = fits.getdata(secat_filename,2)
            self.secat0 = self.secat
            # get median fwhm of image
            # for some images, this comes back as zero, and I don't know why
            fwhm = np.median(self.secat['FWHM_IMAGE'])*pixelscale
            
            
            t = 'sex ' + self.image + ' -c '+defaultcat+' -CATALOG_NAME ' + froot + '.cat -MAG_ZEROPOINT 0 -SATUR_LEVEL '+str(ADUlimit)+' -SEEING_FWHM '+str(fwhm)
            if float(fwhm) == 0:
                print('WARNING: measured FWHM is zero!')
            print('running SE again with new FWHM to get better estimate of CLASS_STAR')
        else:
            t = 'sex ' + self.image + ' -c '+defaultcat+' -CATALOG_NAME ' + froot + '.cat -MAG_ZEROPOINT 0 -SATUR_LEVEL '+str(ADUlimit)+' -SEEING_FWHM '+args.fwhm
            print(t)
            print('running SE w/user input for FWHM to get better estimate of CLASS_STAR')            
        #############################################################
        # rerun Source Extractor catalog with updated SEEING_FWHM
        #############################################################

        #print(t)
        os.system(t)

        ###################################
        # Read in Source Extractor catalog
        ###################################

        secat_filename = froot+'.cat'
        self.secat = fits.getdata(secat_filename,2)

        
        ###################################
        # get max/min RA and DEC for the image
        ###################################

        minRA = min(self.secat['ALPHA_J2000'])
        maxRA = max(self.secat['ALPHA_J2000'])
        minDEC = min(self.secat['DELTA_J2000'])
        maxDEC = max(self.secat['DELTA_J2000'])
        self.centerRA = 0.5*(minRA + maxRA)
        self.centerDEC = 0.5*(minDEC + maxDEC)
        #radius = np.sqrt((maxRA- centerRA)**2 + (maxDEC - centerDEC)**2)
        #print(radius)

        # NOTE - radius is with width of the rectangular
        # search area.  This is not a circular search, as I orginally thought.
        self.radius = max((maxRA - minRA), (maxDEC - minDEC))
    def get_panstarrs(self):

        ###################################
        # get Pan-STARRS catalog over the same region
        ###################################

        self.pan = panstarrs_query(self.centerRA, self.centerDEC, self.radius)
    def match_coords(self):
        ###################################
        # match Pan-STARRS1 data to Source Extractor sources
        # remove any objects that are saturated or non-linear in our r-band image
        ###################################

        pancoords = SkyCoord(self.pan['RAJ2000'],self.pan['DEJ2000'],frame='icrs')
        secoords = SkyCoord(self.secat['ALPHA_J2000']*u.degree,self.secat['DELTA_J2000']*u.degree,frame='icrs')

        index,dist2d,dist3d = pancoords.match_to_catalog_sky(secoords)

        # only keep matches with matched RA and Dec w/in 5 arcsec
        self.matchflag = dist2d.degree < 5./3600


        self.matchedarray1=np.zeros(len(pancoords),dtype=self.secat.dtype)
        self.matchedarray1[self.matchflag] = self.secat[index[self.matchflag]]

        ###################################
        # remove any objects that are saturated, have FLAGS set, galaxies,
        # must have 14 < r < 17 according to Pan-STARRS
        ###################################


        self.fitflag = self.matchflag  & (self.pan['rmag'] > 9.) & (self.matchedarray1['FLAGS'] <  5) & (self.pan['Qual'] < 64)  & (self.matchedarray1['CLASS_STAR'] > 0.95) #& (self.pan['rmag'] < 15.5) #& (self.matchedarray1['MAG_AUTO'] > -11.)

        # for WFC on INT, restrict area to central region
        # to avoid top chip and vignetted regions
        if self.instrument == 'i':
            self.goodarea_flag = (self.matchedarray1['X_IMAGE'] > self.keepsection[0]) & \
                (self.matchedarray1['X_IMAGE'] < self.keepsection[1]) & \
                (self.matchedarray1['Y_IMAGE'] > self.keepsection[2]) & \
                (self.matchedarray1['Y_IMAGE'] < self.keepsection[3])
            self.fitflag = self.fitflag & self.goodarea_flag
                
        if self.filter == 'R':
            ###################################
            # Calculate Johnson R
            # from http://www.sdss3.org/dr8/algorithms/sdssUBVRITransform.php
            ###################################
            self.R = self.pan['rmag'] + (-0.153)*(self.pan['rmag']-self.pan['imag']) - 0.117

            ###################################
            # Other transformations from 
            # https://arxiv.org/pdf/1706.06147.pdf
            # R - r = C0 + C1 x (r-i)  (-0.166, -0.275)
            # R - r = C0 + C1 x (g-r)  (-0.142, -0.166)
            ###################################
            #
            if self.useri:
                self.R = self.pan['rmag'] + (-0.166)*(self.pan['rmag']-self.pan['imag']) - 0.275
            else:
                self.R = self.pan['rmag'] + (-0.142)*(self.pan['gmag']-self.pan['rmag']) - 0.142

        else:
            self.R = self.pan['rmag']
    def plot_fitresults(self, x, y, yerr=None, polyfit_results = [0,0]):
        # plot best-fit results
        yfit = np.polyval(polyfit_results,x)
        residual = (yfit - y)
        plt.figure(figsize=(8,8))
        plt.title(self.image)
        plt.subplot(2,1,1)
        if len(yerr) < len(y): 
            plt.plot(x,y,'bo',label='MAG_AUTO')
            
        else:
            plt.errorbar(x,y,yerr=yerr,fmt='bo',ecolor='b',label='SE MAG')
        plt.xlabel('Pan-STARRS r',fontsize=16)
        plt.ylabel('SE R-band MAG',fontsize=16)
        xl = np.linspace(14,17,10)
        yl = np.polyval(polyfit_results,xl)
        s = 'fit: y = %.2f PAN + %.2f'%(polyfit_results[0],polyfit_results[1])
        plt.plot(xl,yl,'k--',label=s)
        plt.legend()
        
        plt.subplot(2,1,2)
        s = 'std = %.4f'%(np.std(residual))
        if len(yerr) < len(y):
            plt.plot(x,residual, 'ko',label=s)
            
        else:
            plt.errorbar(x,residual,yerr=yerr,fmt='None',ecolor='b',label='SE MAG')
        plt.xlabel('Pan-STARRS r',fontsize=16)
        plt.ylabel('YFIT - SE R-band MAG',fontsize=16)
        plt.legend()
        plt.axhline(y=0,color='r')
        plt.savefig('getzp-fig2.png')

    def fitzp(self,plotall=False):
        ###################################
        # Solve for the zeropoint
        ###################################

        # plot Pan-STARRS r mag on x axis, observed R-mag on y axis
        flag = self.fitflag
        c = np.polyfit(self.pan['rmag'][flag],self.matchedarray1['MAG_AUTO'][flag],1)

        if plotall:
            plt.figure(figsize=(6,4))
            plt.title(self.image)
            plt.plot(self.pan['rmag'][flag],self.matchedarray1['MAG_AUTO'][flag],'bo')
            plt.errorbar(self.pan['rmag'][flag],self.matchedarray1['MAG_AUTO'][flag],xerr= self.pan['e_rmag'][flag],yerr=self.matchedarray1['MAGERR_AUTO'][flag],fmt='none')
            plt.plot(self.pan['rmag'][flag],self.matchedarray1['MAG_BEST'][flag],'ro',label='MAG_BEST')
            plt.plot(self.pan['rmag'][flag],self.matchedarray1['MAG_PETRO'][flag],'go',label='MAG_PETRO')
            plt.plot(self.pan['rmag'][flag],self.matchedarray1['MAG_APER'][:,0][flag],'ko',label='MAG_APER')
            plt.xlabel('Pan-STARRS r',fontsize=16)
            plt.ylabel('SE R-band MAG_AUTO',fontsize=16)

            xl = np.linspace(14,17,10)
            yl = np.polyval(c,xl)
            plt.plot(xl,yl,'k--')
            #plt.savefig('getzp-fig2.png')
            #plt.plot(xl,1.2*yl,'k:')
            #print(c)
    
        yfit = np.polyval(c,self.pan['rmag'])
        residual = np.zeros(len(flag))
        ####################################
        ## had been dividing by yfit, but that doesn't make sense
        ## want residual to be in magnitudes
        ## removing yfit normalization
        ####################################
        residual[flag] = (yfit[flag] - self.matchedarray1['MAG_AUTO'][flag])#/yfit[flag]

        self.bestc = np.array([0,0],'f')
        delta = 100.     
        x = self.R[flag] # expected mag from panstarrs
        # fixed radii apertures: [:,0] = 3 pix, [:,1] = 5 pix, [:,2] = 7 pixels

        if self.mag == 0: # this is the default magnitude
            print('Using Aperture Magnitudes')
            y = self.matchedarray1['MAG_APER'][:,self.naper][flag]
            yerr = self.matchedarray1['MAGERR_APER'][:,self.naper][flag]
        elif self.mag == 1:
            print('Using MAG_BEST')
            y = self.matchedarray1['MAG_BEST'][flag]
            yerr = self.matchedarray1['MAGERR_BEST'][flag]
        elif self.mag == 2:
            print('Using MAG_PETRO')
            y = self.matchedarray1['MAG_PETRO'][flag]
            yerr = self.matchedarray1['MAGERR_PETRO'][flag]
        while delta > 1.e-3:
            #c = np.polyfit(x,y,1)
            t = curve_fit(zpfunc,x,y,sigma = yerr)
            # convert to format expected from polyfit
            c = np.array([1.,t[0][0]])
            print('number of points retained = ',sum(flag))
            yfit = np.polyval(c,x)
            residual = (yfit - y)

            if plotall:
                self.plot_fitresults(x,y,yerr=yerr,polyfit_results = c)

    
            # check for convergence
            print('new ZP = {:.3f}, previous ZP = {:.3f}'.format(self.bestc[1],c[1]))
            delta = abs(self.bestc[1] - c[1])
            self.bestc = c
            MAD = 1.48*np.median(abs(residual - np.median(residual)))
            flag =  (abs(residual - np.median(residual)) < self.nsigma*MAD)
            if sum(flag) < 2:
                print('WARNING: ONLY ONE DATA POINT LEFT')
                self.x = x
                self.y = y
                self.residual = residual
                sys.exit()
            #flag =  (abs(residual) < self.nsigma*np.std(residual))
            self.x = x
            self.y = y
            self.residual =residual
            x = x[flag]
            y = y[flag]
            yerr = yerr[flag]
        ###################################
        ##  show histogram of residuals
        ###################################
        plt.figure()
        yplot = self.matchedarray1['MAG_APER'][:,self.naper][self.fitflag]
        magfit = np.polyval(self.bestc,self.R[self.fitflag])
        residual_all = magfit - yplot
        s = '%.3f +/- %.3f'%(np.mean(residual_all),np.std(residual_all))
        crap = plt.hist(residual_all,bins=np.linspace(-.1,.1,20))
        plt.text(0.05,.85,s,horizontalalignment='left',transform=plt.gca().transAxes)
        plt.savefig('getzp-residual-hist.png')

        ###################################
        # Show location of residuals
        ###################################
        plt.figure(figsize=(6,4))
        plt.title(self.image)
        yplot2 = self.matchedarray1['MAG_APER'][:,self.naper]
        magfit2 = np.polyval(self.bestc,self.R)
        residual_all2 = magfit2 - yplot2

        plt.scatter(self.matchedarray1['X_IMAGE'],self.matchedarray1['Y_IMAGE'],c = (residual_all2),vmin=-.05,vmax=.05,s=15)
        plt.colorbar()
        plt.savefig('getzp-position-residuals-all-fig1.png')
        plt.figure(figsize=(6,4))
        plt.title(self.image)

        plt.scatter(self.matchedarray1['X_IMAGE'][self.fitflag],self.matchedarray1['Y_IMAGE'][self.fitflag],c = (residual_all),vmin=-.05,vmax=.05,s=15)
        plt.colorbar()
        plt.savefig('getzp-position-residuals-fitted-fig1.png')

        self.x = x
        self.y = y
        self.yerr = yerr
        self.zpcovar = t[1]
        self.zperr = np.sqrt(self.zpcovar[0][0])
        self.zp = self.bestc[1]
        self.plot_fitresults(x,y,yerr=yerr,polyfit_results = self.bestc)
                
    def update_header(self):
        print('working on this')
        # add best-fit ZP to image header
        im, header = fits.getdata(self.image,header=True)

        # or convert vega zp to AB
        if self.filter == 'R':
            # conversion from Blanton+2007
            # http://www.astronomy.ohio-state.edu/~martini/usefuldata.html
            header.set('PHOTZP',float('{:.3f}'.format(-1.*self.bestc[1]+.21)))
            header.set('LAMB(um)',float(.6442))

        else:
            header.set('PHOTZP',float('{:.3f}'.format(-1.*self.bestc[1])))
            
        header.set('PHOTSYS','AB')
        header.set('FLUXZPJY',float(3631))

        fits.writeto(self.image, im, header, overwrite=True)
if __name__ == '__main__':


    parser = argparse.ArgumentParser(description ='Run sextractor, get Pan-STARRS catalog, and then computer photometric ZP\n \n from within ipython: \n %run ~/github/Virgo/programs/getzp.py --image pointing031-r.coadd.fits --instrument i \n \n The y intercept is -1*ZP. \n \n x and y data can be accessed at zp.x and zp.y in case you want to make additional plots.', formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--image', dest = 'image', default = 'test.coadd.fits', help = 'Image for ZP calibration')
    parser.add_argument('--instrument', dest = 'instrument', default = None, help = 'HDI = h, KPNO mosaic = m, INT = i')
    parser.add_argument('--fwhm', dest = 'fwhm', default = None, help = 'image FWHM in arcseconds.  Default is none, then SE assumes 1.5 arcsec')    
    parser.add_argument('--filter', dest = 'filter', default = 'R', help = 'filter (R or r; use r for Halpha)')
    parser.add_argument('--useri',dest = 'useri', default = False, action = 'store_true', help = 'Use r->R transformation as a function of r-i rather than the g-r relation.  g-r is the default.')
    parser.add_argument('--nexptime', dest = 'nexptime', default = True, action = 'store_false', help = "set this flag if the image is in ADU rather than ADU/s.  Swarp produces images in ADU/s.")
    parser.add_argument('--mag', dest = 'mag', default = 0,help = "select SE magnitude to use when solving for ZP.  0=MAG_APER,1=MAG_BEST,2=MAG_PETRO.  Default is MAG_APER ")
    parser.add_argument('--naper', dest = 'naper', default = 5,help = "select fixed aperture magnitude.  0=10pix,1=12pix,2=15pix,3=20pix,4=25pix,5=30pix.  Default is 5 (30 pixel diameter)")
    parser.add_argument('--nsigma', dest = 'nsigma', default = 2., help = 'number of std to use in iterative rejection of ZP fitting.  default is 2.')
    parser.add_argument('--d',dest = 'd', default ='~/github/HalphaImaging/astromatic/', help = 'Locates path of default config files.  Default is ~/github/HalphaImaging/astromatic')
    parser.add_argument('--fit',dest = 'fitonly', default = False, action = 'store_true',help = 'Do not run SE or download catalog.  just redo fitting.')
    args = parser.parse_args()
    args.nexptime = bool(args.nexptime)
    args.naper = int(args.naper)
    zp = getzp(args.image, instrument=args.instrument, filter=args.filter, astromatic_dir = args.d,norm_exptime = args.nexptime, nsigma = float(args.nsigma), useri = args.useri,naper = args.naper, mag = int(args.mag))
    zp.getzp()
    print('ZP = {:.3f} +/- {:.3f}'.format(-1*zp.zp,zp.zperr))



