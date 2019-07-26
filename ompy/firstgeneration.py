#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Implementation of the first generation method
(Guttormsen, Ramsøy and Rekstad, Nuclear Instruments and Methods in
Physics Research A 255 (1987).)

---

This file is part of oslo_method_python, a python implementation of the
Oslo method.

Copyright (C) 2018 Jørgen Eriksson Midtbø
Oslo Cyclotron Laboratory
jorgenem [0] gmail.com

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
import copy
import logging
import termtables as tt
import numpy as np
from typing import Tuple, Generator
from .matrix import Matrix
from .library import div0
from .rebin import rebin_2D

LOG = logging.getLogger(__name__)
logging.captureWarnings(True)


class FirstGeneration:
    def __init__(self):
        self.statistical_upper = 430.0  # MAMA ThresSta
        self.statistical_lower = 200.0  # MAMA ThresTot
        self.statistical_ratio = 0.3    # MAMA ThresRatio

        # Shift applied to the energy.
        # TODO: Unknown how to pick. Magne described a manual method
        # by looking at the known low energy states
        self.Ex_entry_shift = 200.0

        # Average entry point in ground band for
        # statistical multiplicity
        self.Ex_entry_statistical = 300.0  # MAMA ExEntry0s

        # Average entry point in ground band for
        # total multiplicity
        self.Ex_entry_total = 0.0          # MAMA ExEntry0t

        self.num_iterations = 10

        self.valley_collection: np.ndarray = None
        self.multiplicity_estimation = 'statistical'

    def apply(self, unfolded: Matrix):
        matrix = copy.deepcopy(unfolded)
        # We don't want negative energies
        matrix.cut('Ex', Emin=0.0)

        multiplicities = self.multiplicity(matrix)
        LOG.debug("Multiplicites:\n%s", tt.to_string(
            np.vstack([matrix.Ex, multiplicities.round(2)]).T,
            header=('Ex', 'Multiplicities')
            ))
        assert (multiplicities >= 0).all(), "Bug. Contact developers"

        # Set up initial first generation matrix with
        # normalized Ex rows
        H = self.row_normalized(matrix)
        # Initial weights should also be row normalized
        W = self.row_normalized(matrix)

        sum_counts, _ = matrix.projection('Ex')

        normalization = div0(np.outer(sum_counts, multiplicities),
                             np.outer(multiplicities, sum_counts))

        for iteration in range(self.num_iterations):
            H_old = np.copy(H)
            W_old = np.copy(W)

            H = rebin_2D(H, matrix.Eg, matrix.Ex, 1)

            mat = Matrix(values=H, Ex=matrix.Ex, Eg=matrix.Ex)
            if iteration == 1:
                mat.plot(zscale='log', title=r'$H_{compressed}$',
                        vmin=1e-3, vmax=1e5)

            W = np.zeros_like(H)
            for i in range(W.shape[0]):  # Loop over Ex rows
                W[i, :i] = H[i, i:0:-1]

            if iteration == 1:
                mat = Matrix(values=W, Ex=matrix.Ex, Eg=matrix.Ex)
                mat.plot(zscale='log', title=r'$W$', vmin=1e-3, vmax=1e5)

            # Prevent oscillations
            if iteration > 4:
                W = 0.7*W + 0.3*W_old
            W = np.nan_to_num(W)
            W[W < 0] = 0.0

            # Normalize each row to unity
            W = div0(W, W.sum(axis=1))

            G = (normalization * W) @ matrix.values
            H = matrix.values - G

            diff = np.max(np.abs(H - H_old))
            LOG.info("iter %i/%i: ε = %g", iteration,
                     self.num_iterations, diff)
        final = Matrix(values=H, Eg=matrix.Eg, Ex=matrix.Ex)
        final.state = "firstgen"
        return final

        # fig, ax = plt.subplots(1)
        # ax.pcolormesh(matrix.Eg, matrix.Ex, matrix.values, norm=LogNorm())
        # print(np.sum(H, axis=1)) # Seems to work!

    def multiplicity(self, matrix: Matrix) -> np.ndarray:
        """ Dispatch method returning statistical or total multiplicity

        Args:
            matrix: The matrix to get multiplicities from
        Returns:
            The multiplicities in a row matrix of same dimension
            as matrix.Ex
        """
        if self.multiplicity_estimation == 'statistical':
            return self.multiplicity_statistical(matrix)
        if self.multiplicity_estimation == 'total':
            return self.multiplicity_total(matrix)
        raise AssertionError("Impossible condition")

    def multiplicity_statistical(self, matrix: Matrix) -> np.ndarray:
        """ Finds the multiplicties using Ex above yrast

        Args:
            matrix: The matrix to get the multiplicites from
        Returns:
            The multiplicities in a row matrix of same dimension
            as matrix.Ex
        """
        # Hacky solution (creation of Magne) to exclude
        # difficult low energy regions, while including 2+ decay
        # if 4+ decay is unlikely
        # This is done by using statistical_upper for energies above and
        # statistical lower for energies below, with a sliding threshold
        # inbetween
        values = copy.copy(matrix.values)
        Eg, Ex = np.meshgrid(matrix.Eg, matrix.Ex)
        Ex_prime = Ex * self.statistical_ratio
        slide = np.minimum(np.maximum(Ex_prime,
                                      self.statistical_lower),
                           self.statistical_upper)
        values[slide > Eg] = 0.0

        # 〈Eg〉= ∑ xP(x) = ∑ xN(x)/∑ N(x)
        sum_counts = np.sum(values, axis=1)
        Eg_sum_counts = np.sum(Eg*values, axis=1)
        Eg_mean = div0(Eg_sum_counts, sum_counts)

        # Statistical multiplicity.
        # Entry energy where the statistical γ-cascade ends in the
        # yrast line.
        entry = np.maximum(
            np.minimum(matrix.Ex - self.Ex_entry_shift,
                       self.Ex_entry_statistical),
            0.0)

        multiplicity = div0(matrix.Ex - entry, Eg_mean)
        return multiplicity

    def multiplicity_total(self, matrix: Matrix) -> np.ndarray:
        """ Finds the multiplicties using all of Ex

        Args
            matrix: The matrix to get the multiplicites from
        Returns
            The multiplicities in a row matrix of same dimension
            as matrix.Ex
        """
        # 〈Eg〉= ∑ xP(x) = ∑ xN(x)/∑ N(x)
        sum_counts = np.sum(matrix.values, axis=1)
        Eg_sum_counts = np.sum(matrix.Eg*matrix.values, axis=1)
        Eg_mean = div0(Eg_sum_counts, sum_counts)
        multiplicity = div0(matrix.Ex, Eg_mean)
        multiplicity[multiplicity < 0] = 0
        return multiplicity

    def row_normalized(self, matrix: Matrix) -> np.ndarray:
        """ Set up a diagonal array with constant Ex rows

        Each Ex-row has constant value given as 1/γ where
        γ is the length of the row from 0 Eγ to the diagonal.
        """
        H = np.zeros(matrix.shape)
        for i, j in diagonal_elements(matrix):
            H[i, :j] = 1/max(1, j)
        return H

    @property
    def multiplicity_estimation(self) -> str:
        return self._multiplicity_estimation

    @multiplicity_estimation.setter
    def multiplicity_estimation(self, method: str) -> None:
        if method.lower() in ['statistical', 'total']:
            self._multiplicity_estimation = method.lower()
        else:
            raise ValueError("Expected multiplicity estimation to"
                             " be either 'statistical' or 'total'")


def diagonal_elements(mat: Matrix) -> Generator[Tuple[int, int], None, None]:
    """ Iterates over the last non-zero elements

    Args:
        mat: The matrix to iterate over
    Yields:
        Indicies (i, j) over the last non-zero (=diagonal)
        elements.
    """
    Ny = mat.shape[1]
    for i, row in enumerate(mat.values):
        for j, col in enumerate(reversed(row)):
            if col != 0.0:
                yield i, Ny-j
                break