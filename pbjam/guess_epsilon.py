import numpy as np
import pandas as pd
import os
import emcee
import matplotlib.pyplot as plt
import warnings

from . import PACKAGEDIR

from scipy.stats import gaussian_kde

class epsilon():
    ''' A class to predict epsilon.

    TODO: flesh this out a bit more

    Attributes
    ----------
    method : string
        Sets the method used to estimate epsilon
        Possible methods are ['Vrard', 'KDE']
    vrard_dict : dict
        Stores the Vrard coefficients (for Red Giant stars)
    data_file : string
        The location of the prior data file
    '''
    def __init__(self, method='Vrard'):
        if method not in ('Vrard','KDE'):
            raise ValueError("The `method` parameter must be one of either"
                                "`Vrard` or `KDE`")

        self.method = method
        self.vrard_dict = {'alpha': 0.601, 'beta': 0.632}
        self.data_file = PACKAGEDIR + os.sep + 'data' + os.sep + 'prior_data.csv'
        self.obs = []
        self.seff_offset = 4000.0
        self.samples = []

    def read_prior_data(self):
        ''' Read in the prior data from self.data_file '''
        self.prior_data = pd.read_csv(self.data_file)
        self.prior_data['Seff'] = self.prior_data.Teff \
                                    - self.seff_offset
        self.prior_data['log_Seff'] = np.log10(self.prior_data.Seff)

    def make_kde(self, bw=0.8):
        ''' Takes the prior data and constructs a KDE function '''
        self.cols = ['log_dnu_', 'log_numax', 'log_Seff', 'bp_rp', 'eps_mod']
        self.kde = gaussian_kde(self.prior_data[self.cols].values.T, bw)

    def normal(self, y, mu, sigma):
        ''' Returns normal log likelihood

        Inputs
        ------
        y : real
            observed value
        mu : real
            distribution mean
        sigma : real
            distribution standard deviation

        Returns
        -------
        log likelihood : real
        '''
        if (sigma < 0):
            return 0.0
        return -0.5 * (y - mu)**2 / sigma**2

    def likelihood(self, p):
        ''' Calculates the log likelihood of for the parameters p

        Inputs
        ------
        p : array
            Array of the parameters [log_dnu, log_numax, log_seff, bp_rp, eps]

        Returns
        -------
        like : real
            The log likelihood evaluated at p.

        '''
        log_dnu, log_numax, log_seff, bp_rp, eps = p
        if log_seff < np.log10(4100.0 - self.seff_offset):
            return -np.inf
        # Constraint from prior
        lp = np.log(self.kde(p))
        # Constraint from data
        ld = 0.0
        ld += self.normal(log_dnu, *self.log_obs['dnu'])
        ld += self.normal(log_numax, *self.log_obs['numax'])
        ld += self.normal(log_seff, *self.log_obs['seff'])
        ld += self.normal(bp_rp, *self.log_obs['bp_rp'])

        return lp + ld

    def kde_sampler(self, niter=2000, nwalkers=20):
        ''' Samples from the posterior probability distribution

        p(theta | D) propto p(theta) p(D | theta)

        p(theta) is given by the KDE function of the prior data

        p(D | theta) is given by the observable constraints

        Convergence is far from guaranteed! Samples are drawn using `emcee`.

        Returns
        -------

        chains: flatchain
            The emcee chain of samples from the posterior

        '''
        x0 = [self.log_obs['dnu'][0],
              self.log_obs['numax'][0],
              self.log_obs['seff'][0],
              self.log_obs['bp_rp'][0],
              1.0]
        ndim = len(x0)
        p0 = [np.array(x0) + np.random.rand(ndim)*1e-3 for i in range(nwalkers)]
        sampler = emcee.EnsembleSampler(nwalkers, ndim, self.likelihood)
        sampler.run_mcmc(p0, niter)
        sampler.reset()
        sampler.run_mcmc(p0, niter)
        return sampler.flatchain

    def to_log10(self, x, xerr):
        if xerr > 0:
            return [np.log10(x), xerr/x/np.log(10.0)]
        return [x, xerr]

    def obs_to_log(self, obs):
        self.log_obs = {'dnu': self.to_log10(*self.obs['dnu']),
                        'numax': self.to_log10(*self.obs['numax']),
                        'teff': self.to_log10(*self.obs['teff']),
                        'seff': self.to_log10(*self.obs['seff']),
                        'bprp': *self.obs['bprp']}

    def vrard(self, dnu):
        ''' Calculates epsilon prediction from Vrard 2015
        https://arxiv.org/pdf/1505.07280.pdf

        Uses the equation from Table 1.

        Has no dependence on temperature so not reliable.

        Assumes a fixed uncertainty of 0.1.

        Parameters
        ----------

        dnu: array-like
            Either a len=2 array with [dnu, dnu_uncertainty] or and monte carlo
            version with [[dnu], [dnu_uncertainty]]

        Returns
        -------

        epsilon: array-like
            Either a len=2 list of epsilon and epsilon uncertainty or a
            monte carlo version with [[epsilon], [epsilon_uncertainty]]

        '''
        if len(dnu) == 2:
            unc = 0.1
            return self.vrard_dict['alpha'] + \
                   self.vrard_dict['beta'] * np.log10(dnu[0]), unc
        else:
            unc = 0.1 * np.ones(len(dnu))
            return self.vrard_dict['alpha'] + \
                   self.vrard_dict['beta'] * np.log10(dnu), unc

    def vrard_predict(self, n, dnu, npts=10000):
        '''
        Predict the l=0 mode frequencies using vrard_dict

        Parameters
        ----------

        n: numpy-array
            A numpy array of radial orders

        dnu: array-like
            The estimate of dnu where dnu = [dnu, dnu_uncertainty].

        Returns
        -------
        frequencies: numpy-array
            A numpy array of length len(n) containting the frequency estimates.

        frequencies_unc: numpy-array
            A numpy array of length len(n) containting the frequency estimates
            uncertainties.
        '''
        dnu_mc = np.random.randn(npts) * dnu[1] + dnu[0]
        eps, eps_unc = self.vrard(dnu_mc)
        eps_mc = eps + np.random.randn(npts) * eps_unc
        frequencies_mc = np.array([(nn + eps_mc) * dnu_mc for nn in n])
        return frequencies_mc.mean(axis=1), frequencies_mc.std(axis=1)

    def plot(self, dnu, numax, teff, periodogram):
        '''
        Make a plot of the suggested Vrard epsilon_guess, on top of a
        `lightkurve` periodogram object passed by the user.

        Parameters
        ----------

        dnu: array-like
            An array-like with [dnu, dnu_uncertainty]

        numax: array-like
            An array-like with [numax, numax_uncertainty]

        teff:  array-like
            An array-like with [teff, teff_uncertainty]

        periodogram: Periodogram
            A lightkurve Periodogram object for plotting.

        '''
        fig, ax = plt.subplots(figsize=[16,9])
        periodogram.plot(ax=ax)
        f = periodogram.frequency.value
        nmin = f.min() / dnu[0]
        nmax = f.max() / dnu[0]
        self.n = np.arange(nmin-1, nmax+1, 1)
        if self.method == 'Vrard':
            freq, freq_unc = self.vrard_predict(self.n, dnu)
        elif self.method == 'KDE':
            freq, freq_unc = self.kde_predict(self.n, dnu, numax, teff)
        for i in range(len(self.n)):
            ax.axvline(freq[i], c='k', linestyle='--', zorder=0, alpha=0.3)
            y = 10 * np.exp(-0.5 * (freq[i] - f)**2 / freq_unc[i]**2)
            #ax.plot(f, 10 * np.exp(-0.5 * (freq[i] - f)**2 / freq_unc[i]**2),
            #            c='k', alpha=0.5)
            ax.fill_between(f, y, alpha=0.3, facecolor='r', edgecolor='none')
        ax.set_xlim([f.min(), f.max()])
        ax.set_ylim([0, periodogram.power.value.max()])

    def kde_predict(self, n, dnu=[1, -1], numax=[1, -1], teff=[1, -1]):
        '''
        Predict the frequencies from the kde method samples

        Parameters
        ----------

        n: numpy_array
            The radial order
        dnu : [real, real]
            Large frequency spacing and uncertainty
        numax : [real, real]
            Frequency of maximum power and uncertainty
        teff : [real, real]
            Stellar effective temperature and uncertainty

        Returns
        -------
        frequencies: numpy-array
            A numpy array of length len(n) containting the frequency estimates.

        frequencies_unc: numpy-array
            A numpy array of length len(n) containting the frequency estimates
            uncertainties.
        '''
        if self.samples == []:
            _, _ = self(dnu, numax, teff)
        dnu = self.samples[:, 0]
        eps = self.samples[:, 3]
        freq = np.array([(nn + eps) * 10**dnu for nn in n])
        return freq.mean(axis=1), freq.std(axis=1)

    def __call__(self, dnu=[1, -1], numax=[1, -1], teff=[1, -1], bp_rp=[1, -1]):
        ''' Calls the relevant defined method and returns an estimate of
        epsilon.

        Note: The call function creates a seff observable that is just
        the (Teff - self.seff_offset).  The reason for this is to put
        the Teff dynamic range into a more useful range that has
        characteristics that are somewhat consistent with the dex
        uncertainty of the rest of the observables.

        Inputs
        ------
        dnu : [real, real]
            Large frequency spacing and uncertainty
        numax : [real, real]
            Frequency of maximum power and uncertainty
        teff : [real, real]
            Stellar effective temperature and uncertainty
        bp_rp : [real, real]
            The Gaia Gbp - Grp color value and uncertainty (probably ~< 0.01 dex)
        Returns
        -------
        result : array-like
            [estimate of epsilon, unceritainty on estimate]
        '''
        if self.method == 'Vrard':
            if numax[0] > 288.0:
                warnings.warn('Vrard method really only valid for Giants.')
                return self.vrard(dnu)[0], 1.0
            return self.vrard(dnu)

        self.obs = {'dnu': dnu,
                    'numax': numax,
                    'teff': teff,
                    'seff': [teff[0] - self.seff_offset, teff[1]],
                    'bp_rp': bp_rp}
        if self.method == 'KDE':
            if numax[0] > 288.0:
                warnings.warn('Not yet implemented for SC stars')
            self.read_prior_data()
            self.obs_to_log(self.obs)
            self.make_kde()
            self.samples = self.kde_sampler()
            return [self.samples[:,3].mean(), self.samples[:,3].std()]
