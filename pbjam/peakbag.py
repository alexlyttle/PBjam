#import matplotlib
#matplotlib.use('Agg')

import numpy as np
import pymc3 as pm
import matplotlib.pyplot as plt
import warnings

class peakbag():
    """
    Class for PBjam peakbagging.

    This class allows for simple manipulation of the data, the fitting of a
    pymc3 model to the data, and some plotting of results functionality.

    Parameters
    ----------
    f : float, array
        Array of frequency bins of the spectrum (muHz). Truncated to the range
        around numax.
    snr : float, array
        Array of SNR values for the frequency bins in f (dimensionless).
    asy_result : asy_result
        The result from the asy_peakbag method.

    Attributes
    ----------
    f : float, array
        Array of frequency bins of the spectrum (muHz). Truncated to the range
        around numax.
    snr : float, array
        Array of SNR values for the frequency bins in f (dimensionless).
    asy_result : asy_result
        The result from the asy_peakbag method.


    Example useage:
        from pbjam import star
        from pbjam import peakbag
        import pymc3 as pm

        # ... define a star in the pbjam star class ...
        star.asymptotic_modeid(norders = 7)
        pb = peakbag.peakbag(star.f, star.s, star.asy_result)
        pb.sample(model_type='width_gp', cores=4, tune=5000)
        pm.summary(pb.samples)
    """
    def __init__(self, f, snr, asy_result, init=True):
        self.f = f
        self.snr = snr
        self.asy_result = asy_result

        if init:
            self.make_start()
            self.trim_ladder()
        self.gp0 = []

    def make_start(self):
        """
        Function uses the information in self.asy_result (the result of the
        asymptotic peakbagging) and builds a disctionary of starting values
        for the peakbagging methods.
        """
        l0 = self.asy_result['modeID'].loc[self.asy_result['modeID'].ell == 0].nu_med.values.flatten()
        l2 = self.asy_result['modeID'].loc[self.asy_result['modeID'].ell == 2].nu_med.values.flatten()
        l0, l2 = self.remove_outsiders(l0, l2)
        width = 10**(np.ones(len(l0)) * self.asy_result['summary'].loc['mean'].mode_width).flatten()
        height =  (10**self.asy_result['summary'].loc['mean'].env_height * \
                 np.exp(-0.5 * (l0 - self.asy_result['summary'].loc['mean'].numax)**2 /
                 (10**self.asy_result['summary'].loc['mean'].env_width)**2)).flatten()
        self.start = {'l0': l0,
                      'l2': l2,
                      'width0': width,
                      'width2': width,
                      'height0': height,
                      'height2': height*0.7,
                      'back': np.ones(len(l0))}
        self.n = np.linspace(0.0, 1.0, len(self.start['l0']))[:, None]

    def remove_outsiders(self, l0, l2):
        sel = np.where(np.logical_and(l0 < self.f.max(), l0 > self.f.min()))
        return l0[sel], l2[sel]

    def trim_ladder(self, lw_fac=10, extra=0.01):
        """
        This function selects only the orders in the ladders that have modes
        that age to be fitted, i.e., it trims the ladder.
        """
        d02 = self.asy_result['summary'].loc['mean'].d02
        d02_lw = d02 + lw_fac * 10**self.asy_result['summary'].loc['mean'].mode_width
        w = d02_lw + (extra * self.asy_result['summary'].loc['mean'].dnu)
        bw = self.f[1] - self.f[0]
        w /= bw
        ladder_trim_f = np.zeros([len(self.start['l0']), int(w)])
        ladder_trim_p = np.zeros([len(self.start['l0']), int(w)])
        for idx, freq in enumerate(self.start['l0']):
            loc_mid_02 = np.argmin(np.abs(self.f - (freq - d02/2.0)))
            if loc_mid_02 == 0:
                # TODO warnings.warn('Possible problem with frequency range! Check ...')
                # What if mode outside of frequency range???
                print(freq, d02/2.0, self.f.min, self.f.max)
                print('Holy cow batman - mode outside frequency range')
            ladder_trim_f[idx, :] = \
                self.f[loc_mid_02 - int(w/2): loc_mid_02 - int(w/2) + int(w)]
            ladder_trim_p[idx, :] = \
                self.snr[loc_mid_02 - int(w/2): loc_mid_02 - int(w/2) + int(w) ]
        self.ladder_f = ladder_trim_f
        self.ladder_p = ladder_trim_p

    def lor(self, freq, w, h):
        """
        This function calculates a lorentzian for each rung of the frequency
        ladder.  The ladder is a 2D array.  freq, w, and h should be 1D arrays
        of length that matches the height of the ladder.  No checkes are made
        for this so as to reduce overheads.

         Parameters
         ----------
         freq : float, array
            A length H array of Lorentzian central frequencies where H is the
            height of self.ladder_f .
         w : float, array
            A length H array of Lorentzian widths.
         h : float, array
            A length H array of Lorentzian heights.

        Returns
        -------
        lorentzians : float, ladder
           A ladder containing one Lorentzian per rung.
        """
        diff = (self.ladder_f.T - freq)**2
        norm = 1.0 + 4.0 / w**2 * diff
        return h / norm

    def model(self, l0, l2, width0, width2, height0, height2, back):
        """
        Calcuates a simple model of a flat backgroud plus two lorentzians
        for each rung of self.ladder_f .

        Parameters
        ----------
        l0 : float, array
            A length H array of l=0 mode central frequencies where H is the
            height of self.ladder_f .
        l2 : float, array
            A length H array of l=2 mode central frequencies.
        width0 : float, array
            A length H array of l=0 mode widths.
        width2 : float, array
            A length H array of l=2 mode widths.
        height0 : float, array
            A length H array of l=0 mode heights.
        height2 : float, array
            A length H array of l=2 mode heights.
        back : float, array
            A length H array of background values.

        Returns
        -------
        mod : float, ladder
            A ladder containing the calculted model.
        """
        mod = np.ones(self.ladder_f.shape).T * back
        mod += self.lor(l0, width0, height0)
        mod += self.lor(l2, width2, height2)
        return mod.T

    def plot_start_model(self):
        """
        Plots the model generated from the starting parameters
        """
        mod = self.model(self.start['l0'],
                         self.start['l2'],
                         self.start['width0'],
                         self.start['width2'],
                         self.start['height0'],
                         self.start['height2'],
                         self.start['back'])
        n = self.ladder_p.shape[0]
        fig, ax = plt.subplots(n, figsize=[16,9])
        for i in range(n):
            ax[i].plot(self.ladder_f[i, :], self.ladder_p[i, :], c='k')
            ax[i].plot(self.ladder_f[i, :], mod[i, :], c='r')
        return fig

    def simple(self):
        """
        Creates a simple peakbagging model in pymc3's self.pm_model which is
        an instance of pm.Model().

        The simple model has three parameters per mode (freq, w, h) and one
        back parameter per rung of the frequency ladder.

        All parameters are independent.  For a model with additional constraints
        see model_gp.

        Priors on parameters are defined as follows:
            l0 ~ Normal(start[l0], dnu*0.1)
            l2 ~ Normal(start[l2], dnu*0.1)
            width0 ~ HalfNormal(wfac * start[width0])
            width2 ~ HalfNormal(wfac * start[width2])
            height0 ~ HalfNormal(hfac * start[height0])
            height2 ~ HalfNormal(hfac * start[height2])
            back ~ Normal(1, 0.2)

        The likelihood function of the observed data is dealt with using a
        Gamma distribution where alpha=1 and beta=1/limit where limit is the
        model of the spectrum proposed.  Using this gamma distirbution is the
        equivalent of stating that observed/model is distributed as chi squared
        two degrees of freedom.
        """
        dnu = self.asy_result['summary'].loc['mean'].dnu
        self.pm_model = pm.Model()
        with self.pm_model:
            l0 = pm.Normal('l0', self.start['l0'], dnu*0.1,
                              shape=len(self.start['l0']))
            l2 = pm.Normal('l2', self.start['l2'], dnu*0.1,
                              shape=len(self.start['l2']))
            width0 = pm.Lognormal('width0', np.log(self.start['width0']), 1.0,
                                    shape=len(self.start['l2']))
            width2 = pm.Lognormal('width2', np.log(self.start['width2']), 1.0,
                                    shape=len(self.start['l2']))
            height0 = pm.Lognormal('height0', np.log(3),
                                    10.0,
                                    shape=len(self.start['l2']))
            height2 = pm.Lognormal('height2', np.log(3),
                                    10.0,
                                    shape=len(self.start['l2']))
            back = pm.Lognormal('back', np.log(1.0), 0.5,
                                    shape=len(self.start['l2']))

            limit = self.model(l0, l2, width0, width2, height0, height2, back)
            yobs = pm.Gamma('yobs', alpha=1, beta=1.0/limit, observed=self.ladder_p)

    def model_hr(self):
        dnu = self.asy_result['summary'].loc['mean'].dnu
        self.pm_model = pm.Model()
        with self.pm_model:
            l0 = pm.Normal('l0', self.start['l0'], dnu*0.1,
                              shape=len(self.start['l0']))
            l2 = pm.Normal('l2', self.start['l2'], dnu*0.1,
                              shape=len(self.start['l2']))
            width0 = pm.Lognormal('width0', np.log(self.start['width0']), 0.2,
                                    shape=len(self.start['l2']))
            width2 = pm.Lognormal('width2', np.log(self.start['width2']), 0.2,
                                    shape=len(self.start['l2']))
            height0 = pm.Lognormal('height0', np.log(self.start['height0']),
                                    0.4,
                                    shape=len(self.start['l2']))
            height20 = pm.Lognormal('height20', np.log(0.7), 0.1,
                                    shape=len(self.start['l2']),
                                    startval=np.one(len(self.start['l2']))*0.7)
            height2 = pm.Deterministic('height2', height0 * height20)
            back = pm.Normal('back', 1.0, 0.3,
                                    shape=len(self.start['l2']))
            limit = self.model(l0, l2, width0, width2, height0, height2, back)
            yobs = pm.Gamma('yobs', alpha=1, beta=1.0/limit, observed=self.ladder_p)

    def model_gp(self):
        """
        TODO
        """
        warnings.warn('This model is developmental - use carefully')
        dnu = self.asy_result['summary'].loc['mean'].dnu
        self.pm_model = pm.Model()

        hfac = 10.0
        wfac = 1.0
        with self.pm_model:
            l0 = pm.Normal('l0', self.start['l0'], dnu*0.1,
                              shape=len(self.start['l0']))
            l2 = pm.Normal('l2', self.start['l2'], dnu*0.1,
                              shape=len(self.start['l2']))
            # Place a GP over the l=0 mode widths ...
            m0 = pm.Normal('gradient0', 0, 10)
            c0 = pm.Normal('intercept0', 0, 10)
            sigma0 = pm.Lognormal('sigma0', np.log(1.0), 0.3)
            ls = pm.Lognormal('ls', np.log(0.3), 0.2)
            mean_func0 = pm.gp.mean.Linear(coeffs=m0, intercept=c0)
            cov_func0 = sigma0 * pm.gp.cov.ExpQuad(1, ls=ls)
            self.gp0 = pm.gp.Latent(cov_func=cov_func0,
                                   mean_func=mean_func0)
            ln_width0 = self.gp0.prior('ln_width0', X=self.n)
            width0 = pm.Deterministic('width0', pm.math.exp(ln_width0))
            # and on the l=2 mode widths
            m2 = pm.Normal('gradient2', 0, 10)
            c2 = pm.Normal('intercept2', 0, 10)
            sigma2 = pm.Lognormal('sigma2', np.log(1.0), 0.3)
            mean_func2 = pm.gp.mean.Linear(coeffs=m2, intercept=c2)
            cov_func2 = sigma2 * pm.gp.cov.ExpQuad(1, ls=ls)
            self.gp2 = pm.gp.Latent(cov_func=cov_func2,
                                   mean_func=mean_func2)
            ln_width2 = self.gp2.prior('ln_width2', X=self.n)
            width2 = pm.Deterministic('width2', pm.math.exp(ln_width2))
            #Carry on
            height0 = pm.Lognormal('height0', np.log(self.start['height0']),
                                    0.4,
                                    shape=len(self.start['l2']))
            height2 = pm.Lognormal('height2', np.log(self.start['height2']),
                                    0.4,
                                    shape=len(self.start['l2']))
            back = pm.Normal('back', 1.0, 0.3,
                                    shape=len(self.start['l2']))

            limit = self.model(l0, l2, width0, width2, height0, height2, back)
            yobs = pm.Gamma('yobs', alpha=1, beta=1.0/limit, observed=self.ladder_p)

    def sample(self, model_type='simple',
                     tune=2000,
                     target_accept=0.8,
                     cores=1,
                     maxiter=4,
                     advi=True):
        """
        Function to perform the sampling of a defined model.

        Parameters
        ----------
        model_type : str
            Defaults to 'simple'.
            Can be either 'simple' or 'model_gp' which sets the type of model
            to be fitted to the data.
        tune : int
            Numer of tuning steps passed to pm.sample
        target_accept : float
            Target acceptance fraction passed to pm.sample
        cores : int
            Number of cores to use - passed to pm.sample

        """
        if model_type == 'simple':
            self.simple()
        elif model_type == 'model_gp':
            self.model_gp()
        elif model_type == 'model_hr':
            self.model_hr()
        else:
            print('Model not defined ')

        if advi:
            with self.pm_model:
                mean_field = pm.fit(n=100000, method='fullrank_advi',
                                    start=self.start,
                                    callbacks=[pm.callbacks.CheckParametersConvergence(every=1000,
                                                                                       diff='absolute',
                                                                                       tolerance=0.01)])
                self.samples = mean_field.sample(1000)

        else:
            Rhat_max = 10
            niter = 1
            while Rhat_max > 1.05:
                if niter > maxiter:
                    warnings.warn('Did not converge!')
                    break
                with self.pm_model:
                    self.samples = pm.sample(tune=tune * niter,
                                             #start=self.start,
                                             cores=cores,
                                             init='adapt_diag',
                                             target_accept=target_accept,
                                             progressbar=True)
                Rhat_max = np.max([v.max() for k, v in pm.diagnostics.gelman_rubin(self.samples).items()])
                niter += 1


    def traceplot(self):
        pm.traceplot(self.samples)

    def plot_linewidth(self, thin=10):
        """
        TODO
        """
        fig, ax = plt.subplots(1, 2, figsize=[16,9])

        if self.gp0 != []:
            from pymc3.gp.util import plot_gp_dist

            n_new = np.linspace(-0.2, 1.2, 100)[:,None]
            with self.pm_model:
                f_pred0 = self.gp0.conditional("f_pred0", n_new)
                f_pred2 = self.gp2.conditional("f_pred2", n_new)
                self.pred_samples = pm.sample_posterior_predictive(self.samples,
                               vars=[f_pred0, f_pred2], samples=1000)
            plot_gp_dist(ax[0], self.pred_samples["f_pred0"], n_new)
            plot_gp_dist(ax[1], self.pred_samples["f_pred2"], n_new)

            for i in range(0, len(self.samples), thin):
                ax[0].scatter(self.n,
                              self.samples['ln_width0'][i, :], c='k', alpha=0.3)
                ax[1].scatter(self.n,
                              self.samples['ln_width2'][i, :], c='k', alpha=0.3)


        else:
            for i in range(0, len(self.samples), thin):
                ax[0].scatter(self.n,
                              np.log(self.samples['width0'][i, :]), c='k', alpha=0.3)
                ax[1].scatter(self.n,
                              np.log(self.samples['width2'][i, :]), c='k', alpha=0.3)

        ax[0].set_xlabel('normalised order')
        ax[1].set_xlabel('normalised order')
        ax[0].set_ylabel('ln line width')
        ax[1].set_ylabel('ln line width')
        ax[0].set_title('Radial modes')
        ax[1].set_title('Quadrupole modes')
        return fig

    def plot_height(self, thin=10):
        """
        TODO
        """
        fig, ax = plt.subplots(figsize=[16,9])
        for i in range(0, len(self.samples), thin):
            ax.scatter(self.samples['l0'][i, :], self.samples['height0'][i, :])
            ax.scatter(self.samples['l2'][i, :], self.samples['height2'][i, :])
        return fig

    def plot_fit(self, thin=10, alpha=0.2):
        """
        TODO
        """
        n = self.ladder_p.shape[0]
        fig, ax = plt.subplots(n, figsize=[16,9])
        for i in range(n):
            for j in range(0, len(self.samples), thin):
                mod = self.model(self.samples['l0'][j],
                                 self.samples['l2'][j],
                                 self.samples['width0'][j],
                                 self.samples['width2'][j],
                                 self.samples['height0'][j],
                                 self.samples['height2'][j],
                                 self.samples['back'][j])
                ax[i].plot(self.ladder_f[i, :], mod[i, :], c='r', alpha=alpha)
            ax[i].plot(self.ladder_f[i, :], self.ladder_p[i, :], c='k')
            ax[i].set_xlim([self.ladder_f[i, 0], self.ladder_f[i, -1]])
        ax[n-1].set_xlabel(r'Frequency ($\mu \rm Hz$)')
        fig.tight_layout()
        return fig
