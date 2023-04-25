"""Discrete Surfaces with Elastic metrics.

Lead author: Emmanuel Hartman
"""

import os

os.environ["GEOMSTATS_BACKEND"] = "pytorch"
import geomstats.backend as gs
import numpy as np
import torch
import trimesh
from geomstats.geometry.hypersphere import Hypersphere
from geomstats.geometry.manifold import Manifold
from geomstats.geometry.riemannian_metric import RiemannianMetric
from scipy.optimize import minimize
from torch.autograd import grad


class DiscreteSurfaces(Manifold):
    r"""Space of parameterized discrete surfaces.

    Each surface is sampled with fixed n_vertices vertices and n_faces faces
    in $\mathbb{R}^3$.

    Each individual surface is represented by a 2d-array of shape `[
    n_vertices, 3]`. This space corresponds to the space of immersions
    defined below, i.e. the
    space of smooth functions from a template to manifold $M$ into  $\mathbb{R}^3$,
    with non-vanishing Jacobian.
    .. math::
        Imm(M,\mathbb{R}^3)=\{ f \in C^{\infty}(M, \mathbb{R}^3)
        \|Df(x)\|\neq 0 \forall x \in M \}.

    Parameters
    ----------
    faces : integer array-like, shape=[n_faces, 3]

    Attributes
    ----------
    faces : integer array-like, shape=[n_faces, 3]
    """

    def __init__(self, faces, **kwargs):
        """Create an object."""
        ambient_dim = 3
        self.dim = (gs.amax(faces) + 1) * ambient_dim
        self.faces = faces
        self.n_faces = len(faces)
        self.n_vertices = int(gs.amax(self.faces) + 1)

    def belongs(self, point, atol=gs.atol):
        """Test whether a point belongs to the manifold.

        Checks that vertices are inputed in proper form and are
        consistent with the mesh structure.

        Also checks if the discrete surface has degenerate triangles.
        A "degenerate triangle" is a very small (and unneccessary)
        triangle. Thus, to test for very small (degenerate)
        triangles, we test for very small areas.

        Parameters
        ----------
        point : array-like, shape=[n_vertices, 3]
            Surface, i.e. the vertices of its triangulation.
        atol : float
            Absolute tolerance.
            Optional, default: backend atol.

        Returns
        -------
        belongs : bool
            Boolean evaluating if point belongs to the space of discrete
            surfaces.
        """
        if point.shape[-1] != 3:
            return False
        if point.shape[-2] != self.n_vertices:
            return False
        smallest_area = min(self.face_areas(point))
        if smallest_area < atol:
            return False
        return True

    def is_tangent(self, vector, base_point, atol=gs.atol):
        """Check whether the vector is tangent at base_point.

        Tangent vectors are identified with points of the vector space so
        this checks the shape of the input vector.

        Parameters
        ----------
        vector : array-like, shape=[..., n_vertices, 3]
            Vector.
        base_point : array-like, shape=[..., n_vertices, 3]
            Point in the vector space.
        atol : float
            Absolute tolerance.
            Optional, default: backend atol.

        Returns
        -------
        is_tangent : array-like, shape=[...,]
            Boolean denoting if vector is a tangent vector at the base point.
        """
        return vector.shape[-1] == 3 and vector.shape[-2] == self.n_vertices

    def to_tangent(self, vector, base_point):
        """Project a vector to a tangent space of the manifold.

        Parameters
        ----------
        vector : array-like, shape=[..., *point_shape]
            Vector.

        base_point : array-like, shape=[..., *point_shape]
            Point on the manifold.

        Returns
        -------
        tangent_vec : array-like, shape=[..., *point_shape]
            Tangent vector at base point.
        """
        raise NotImplementedError("to tangent is not implemented for discrete surfaces")

    def projection(self, point):
        """Project a point to the manifold.

        Parameters
        ----------
        point: array-like, shape[..., *point_shape]
            Point.

        Returns
        -------
        point: array-like, shape[..., *point_shape]
            Point.
        """
        raise NotImplementedError("projection is not implemented for discrete surfaces")

    def random_point(self, n_samples=1):
        """Sample discrete surfaces.

        This sample random discrete surfaces with the correct number of vertices.

        Parameters
        ----------
        n_samples : int
            Number of surfaces to sample.
            Optional, Default=1

        Returns
        -------
        vertices :  array-like, shape=[n_samples, n_vertices, 3]
            Vertices for a batch of points in the space of discrete surfaces.
        """
        sphere = Hypersphere(dim=2, default_coords_type="extrinsic")
        vertices = sphere.random_uniform(n_samples * self.n_vertices)
        vertices = gs.reshape(vertices, (n_samples, self.n_vertices, 3))
        return vertices

    def vertex_areas(self, point):
        """Compute vertex areas for a triangulated surface.

        Parameters
        ----------
        point : array-like, shape=[n_verticesx3]
             Surface, i.e. the vertices of its triangulation.

        Returns
        -------
        vertareas :  array-like, shape=[n_verticesx1]
            vertex areas
        """
        n_vertices = point.shape[0]
        face_coordinates = point[self.faces]
        vertex0, vertex1, vertex2 = (
            face_coordinates[:, 0],
            face_coordinates[:, 1],
            face_coordinates[:, 2],
        )
        len_edge_12 = gs.linalg.norm((vertex1 - vertex2), axis=1)
        len_edge_02 = gs.linalg.norm((vertex0 - vertex2), axis=1)
        len_edge_01 = gs.linalg.norm((vertex0 - vertex1), axis=1)
        half_perimeter = 0.5 * (len_edge_12 + len_edge_02 + len_edge_01)
        area = gs.sqrt(
            (
                half_perimeter
                * (half_perimeter - len_edge_12)
                * (half_perimeter - len_edge_02)
                * (half_perimeter - len_edge_01)
            ).clip(min=1e-6)
        )
        id_vertices = gs.flatten(torch.tensor(self.faces))
        incident_areas = gs.zeros(n_vertices)
        val = gs.flatten(gs.stack([area] * 3, axis=1))
        incident_areas.scatter_add_(0, id_vertices, val)
        vertex_areas = 2 * incident_areas / 3.0
        return vertex_areas

    def get_laplacian(self, point):
        """Compute the mesh Laplacian operator of a surface.

        Note: this function will not return the laplacian at a tangent vector.
        If you define:
        laplacian = self.get_laplacian(point)
        then to get the laplacian at a tangent vector, you need to call:
        laplacian(tangent_vec).
        in other words, this function returns another function.

        The laplacian is evaluated at one of its tangent vectors, tangent_vec.

        Parameters
        ----------
        point  :  array-like, shape=[n_verticesx3]
             Surface, i.e. the vertices of its triangulation.

        Returns
        -------
        laplacian : callable
            Function that will evaluate the mesh Laplacian operator
            at a tangent vector to the surface
        """
        n_vertices, n_faces = point.shape[0], self.faces.shape[0]
        face_coordinates = point[self.faces]
        vertex0, vertex1, vertex2 = (
            face_coordinates[:, 0],
            face_coordinates[:, 1],
            face_coordinates[:, 2],
        )
        len_edge_12 = gs.linalg.norm((vertex1 - vertex2), axis=1)
        len_edge_02 = gs.linalg.norm((vertex0 - vertex2), axis=1)
        len_edge_01 = gs.linalg.norm((vertex0 - vertex1), axis=1)
        half_perimeter = 0.5 * (len_edge_12 + len_edge_02 + len_edge_01)
        area = gs.sqrt(
            (
                half_perimeter
                * (half_perimeter - len_edge_12)
                * (half_perimeter - len_edge_02)
                * (half_perimeter - len_edge_01)
            ).clip(min=1e-6)
        )
        sq_len_edge_12, sq_len_edge_02, sq_len_edge_01 = (
            len_edge_12 * len_edge_12,
            len_edge_02 * len_edge_02,
            len_edge_01 * len_edge_01,
        )
        cot_12 = (sq_len_edge_02 + sq_len_edge_01 - sq_len_edge_12) / area
        cot_02 = (sq_len_edge_12 + sq_len_edge_01 - sq_len_edge_02) / area
        cot_01 = (sq_len_edge_12 + sq_len_edge_02 - sq_len_edge_01) / area
        cot = gs.stack([cot_12, cot_02, cot_01], axis=1)
        cot /= 2.0
        ii = self.faces[:, [1, 2, 0]]
        jj = self.faces[:, [2, 0, 1]]
        id_vertices = gs.reshape(
            gs.stack([torch.tensor(ii), torch.tensor(jj)], axis=0), (2, n_faces * 3)
        )

        def laplacian(tangent_vec):
            """Evaluate the mesh Laplacian operator.

            The operator is evaluated at a tangent vector to the surface.

            Parameters
            ----------
            tangent_vec :  array-like, shape=[n_verticesx3]
                Tangent vector to the triangulated surface.

            Returns
            -------
            laplacian_at_tangent_vec: array-like, shape=[n_verticesx3]
                Mesh Laplacian operator of the triangulated surface applied
                 to one its tangent vector tangent_vec.
            """
            tangent_vec_diff = tangent_vec[id_vertices[0]] - tangent_vec[id_vertices[1]]
            values = gs.stack([gs.flatten(cot)] * 3, axis=1) * tangent_vec_diff
            laplacian_at_tangent_vec = gs.zeros((n_vertices, 3))
            laplacian_at_tangent_vec[:, 0] = laplacian_at_tangent_vec[:, 0].scatter_add(
                0, id_vertices[1, :], values[:, 0]
            )
            laplacian_at_tangent_vec[:, 1] = laplacian_at_tangent_vec[:, 1].scatter_add(
                0, id_vertices[1, :], values[:, 1]
            )
            laplacian_at_tangent_vec[:, 2] = laplacian_at_tangent_vec[:, 2].scatter_add(
                0, id_vertices[1, :], values[:, 2]
            )
            return laplacian_at_tangent_vec

        return laplacian

    def normals(self, point):
        """Compute normals at each face of a triangulated surface.

        Normals are the cross products between edges of each face
        that are incident to its x-coordinate.

        Parameters
        ----------
        point : array-like, shape=[n_vertices, 3]
            Surface, i.e. the vertices of its triangulation.

        Returns
        -------
        normals_at_point : array-like, shape=[n_facesx1]
            Normals of each face of the mesh.
        """
        vertex_0, vertex_1, vertex_2 = (
            gs.take(point, indices=self.faces[:, 0], axis=0),
            gs.take(point, indices=self.faces[:, 1], axis=0),
            gs.take(point, indices=self.faces[:, 2], axis=0),
        )
        normals_at_point = 0.5 * gs.cross(vertex_1 - vertex_0, vertex_2 - vertex_0)
        return normals_at_point

    def surface_one_forms(self, point):
        """Compute the vector valued one-forms.

        The one forms are evaluated at the faces of a triangulated surface.

        in the paper, the one forms are defined by dq_f

        ISSUE: one forms are returning shape: torch.Size([1280, 2, 3])
        but should be torch.Size([1280, 3, 2])
        when i change it to stack along -1 axis, i get linalg error

        Parameters
        ----------
        point :  array-like, shape=[n_vertices, 3]
             One surface, i.e. the vertices of its triangulation.

        Returns
        -------
        one_forms_base_point : array-like, shape=[n_faces, 3, 2]
            One form evaluated at each face of the triangulated surface.
        """
        point = torch.Tensor(point)
        print("shape of point in surface_one_forms: " + str(point.shape))
        vertex_0, vertex_1, vertex_2 = (
            gs.take(point, indices=self.faces[:, 0], axis=0),
            gs.take(point, indices=self.faces[:, 1], axis=0),
            gs.take(point, indices=self.faces[:, 2], axis=0),
        )
        print("vertex_0: " + str(vertex_0.shape))
        print(
            "surface_one_forms: "
            + str(gs.stack([vertex_1 - vertex_0, vertex_2 - vertex_0], axis=-1).shape)
        )
        return gs.stack([vertex_1 - vertex_0, vertex_2 - vertex_0], axis=-1)

    def face_areas(self, point):
        """Compute the areas for each face of a triangulated surface.

        The corresponds to the volume area for the surface metric, that is
        the volume area of the pullback metric of the immersion defining the
        surface metric.

        Parameters
        ----------
        point :  array-like, shape=[n_vertices, 3]
            One surface, i.e. the vertices of its triangulation.

        Returns
        -------
        _ :  array-like, shape=[n_faces,]
            Area computed at each face of the triangulated surface.
        """
        print("face_areas " + str(point.shape))
        surface_metrics = self.surface_metric_matrices(point)
        print("face_areas determinant: " + str(gs.sqrt(gs.linalg.det(surface_metrics))))
        return gs.sqrt(gs.linalg.det(surface_metrics))

    def surface_metric_matrices(self, point):
        """Compute the surface metric matrices.

        The matrices are evaluated at the faces of a triangulated surface.

        The surface metric is the pullback metric of the immersion q
        defining the surface, i.e. of
        the map q: M -> R3, where M is the parameterization manifold.

        In the paper, surface_metric_matrices are denoted by g_f.
        calculated via dq_f*dq_f^T

        Parameters
        ----------
        point : array like, shape=[n_verticesx3]
            One surface, i.e. the vertices of its triangulation.

        Returns
        -------
        _ : array-like, shape=[n_faces, 2, 2]
            Surface metric matrices evaluated at each face of
            the triangulated surface.
        """
        one_forms = self.surface_one_forms(point)
        transposed_one_forms = gs.transpose(one_forms, axes=(0, 2, 1))
        print(
            "surface_metric_matrices in DiscreteSurfaces: "
            + str(gs.matmul(transposed_one_forms, one_forms))
        )
        return gs.matmul(transposed_one_forms, one_forms)


class ElasticMetric(RiemannianMetric):
    """Elastic metric defined a family of second order Sobolev metrics.

    Each individual surface is represented by a 2d-array of shape `[
    n_vertices, 3]`.

    See [HSKCB2022]_ for details.

    Parameters
    ----------
    space : Manifold
        Instantiated DiscreteSurfaces manifold.
    a0 : float
        First order parameter.
    a1 : float
        Stretching parameter.
    b1 : float
        Shearing parameter.
    c1 : float
        Bending parameter.
    d1 : float
        additonal first order parameter.
    a2 : float
        Second order parameter.
    References
    ----------
    .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
    Sobolev metrics: a comprehensive numerical framework",
    arXiv:2204.04238 [cs.CV], 25 Sep 2022
    """

    def __init__(self, space, a0, a1, b1, c1, d1, a2):
        """Create a metric object."""
        self.a0 = a0
        self.a1 = a1
        self.b1 = b1
        self.c1 = c1
        self.d1 = d1
        self.a2 = a2
        self.space = space
        self.n_times = 5

    def inner_product(self, tangent_vec_a, tangent_vec_b, base_point):
        """Inner product between two tangent vectors at a base point.

        g_q^-1 (dh, dh) = tr(dh.g_q^-1 .dhT )

        dh = dhm + dh+ + dh⊥ + dh0,

        dhm = 1/2 dq g_q^-1 (dqT dh + dhT dq) - 1/2 tr(g_q^-1 dqT dh)dq
        dh+ = 1/2 tr(g_q^-1 dqT dh)dq
        dh⊥ = dh - dq g_q^-1 dqT dh
        dh0 = 1/2 dq g_q^-1 (dqT dh - dhT dq)

        xi1_0 in code is dh_0 in paper.
        xi2_0 in code is dk_0 in paper.

        h is a tangent vector at q. dh is the vector [h1-h0, h2-h0, ..., hn-h0]

        Parameters
        ----------
        tangent_vec_a: array-like, shape=[n_vertices, 3]
            Tangent vector at base point.
        tangent_vec_b: array-like, shape=[n_vertices, dim]
            Tangent vector at base point.
        base_point: array-like, shape=[n_vertices, dim]
            Base point.

        Returns
        -------
        inner_product : float
            Inner-product.
        """
        h = tangent_vec_a
        k = tangent_vec_b
        point_a = base_point + h
        point_b = base_point + k
        norm = 0
        if self.a0 > 0 or self.a2 > 0:
            v_areas = self.space.vertex_areas(base_point)
            if self.a2 > 0:
                laplacian_at_base_point = self.space.get_laplacian(base_point)
                norm += self.a2 * gs.sum(
                    gs.einsum(
                        "bi,bi->b",
                        laplacian_at_base_point(h),
                        laplacian_at_base_point(k),
                    )
                    / v_areas
                )
            if self.a0 > 0:
                norm += self.a0 * gs.sum(v_areas * gs.einsum("bi,bi->b", h, k))
        # CHANGE ALERT: changed second self.b1 to be self.d1
        if self.a1 > 0 or self.b1 > 0 or self.c1 > 0 or self.d1 > 0:
            one_forms_base_point = self.space.surface_one_forms(base_point)
            # CHANGE ALERT: switched the order so that it is dq_f*dq_f^T.
            # surface_metrics = gs.matmul(
            #     one_forms_base_point, gs.transpose(one_forms_base_point, axes=(0, 2, 1))
            # )
            surface_metrics = gs.matmul(
                gs.transpose(one_forms_base_point, axes=(0, 2, 1)), one_forms_base_point
            )
            # these are face areas. we know this because a1, b1, c1, d1 are in the face
            # sum in the H2 metric.
            face_areas = gs.sqrt(gs.linalg.det(surface_metrics))
            print("face areas in inner_product: " + str(face_areas))
            normals_at_base_point = self.space.normals(base_point)
            if self.c1 > 0:
                dn1 = self.space.normals(point_a) - normals_at_base_point
                dn2 = self.space.normals(point_b) - normals_at_base_point
                norm += self.c1 * gs.sum(gs.einsum("bi,bi->b", dn1, dn2) * face_areas)
            if self.d1 > 0 or self.b1 > 0 or self.a1 > 0:
                ginv = gs.linalg.inv(surface_metrics)
                one_forms_a = self.space.surface_one_forms(point_a)
                one_forms_b = self.space.surface_one_forms(point_b)
                if self.d1 > 0:
                    xi1 = one_forms_a - one_forms_base_point
                    # QUESTION: Isn't this missing a 1/2 factor?
                    xi1_0 = gs.matmul(
                        gs.matmul(one_forms_base_point, ginv),
                        gs.matmul(gs.transpose(xi1, (0, 2, 1)), one_forms_base_point)
                        - gs.matmul(
                            gs.transpose(one_forms_base_point, axes=(0, 2, 1)), xi1
                        ),
                    )
                    xi2 = one_forms_b - one_forms_base_point
                    xi2_0 = gs.matmul(
                        gs.matmul(one_forms_base_point, ginv),
                        gs.matmul(gs.transpose(xi2, (0, 2, 1)), one_forms_base_point)
                        - gs.matmul(
                            gs.transpose(one_forms_base_point, axes=(0, 2, 1)), xi2
                        ),
                    )
                    norm += self.d1 * gs.sum(
                        gs.einsum(
                            "bii->b",
                            gs.matmul(
                                xi1_0,
                                gs.matmul(ginv, gs.transpose(xi2_0, axes=(0, 2, 1))),
                            ),
                        )
                        * face_areas
                    )
                if self.b1 > 0 or self.a1 > 0:
                    dg1 = (
                        gs.matmul(
                            gs.transpose(one_forms_a, axes=(0, 2, 1)), one_forms_a
                        )
                        - surface_metrics
                    )
                    dg2 = (
                        gs.matmul(
                            gs.transpose(one_forms_b, axes=(0, 2, 1)), one_forms_b
                        )
                        - surface_metrics
                    )
                    ginvdg1 = gs.matmul(ginv, dg1)
                    ginvdg2 = gs.matmul(ginv, dg2)
                    norm += self.a1 * gs.sum(
                        gs.einsum("bii->b", gs.matmul(ginvdg1, ginvdg2)) * face_areas
                    )
                    norm += self.b1 * gs.sum(
                        gs.einsum("bii->b", ginvdg1)
                        * gs.einsum("bii->b", ginvdg2)
                        * face_areas
                    )
        return norm

    def squared_norm(self, vector, base_point):
        """Compute squared norm of a tangent vector at a base point.

        Parameters
        ----------
        vector: array-like, shape=[n_vertices, 3]
            Tangent vector at base point.
        base_point: array-like, shape=[n_vertices, dim]
            Base point.

        Returns
        -------
        squared_norm : float
            Squared Norm.
        """
        return self.inner_product(vector, vector, base_point)

    def stepwise_path_energy(self, path):
        """Compute stepwise path energy of a PL path in the space of discrete surfaces.

        Parameters
        ----------
        path: array-like, shape=[n_times, n_vertices, 3]
            PL path of discrete surfaces.

        Variables:
        ----------
        diff: an array that contains the difference between two consecutive points in the path
        (for example, the first element contains a vector of the differences between the first
        point and the second point)
        midpoints: an array that contains the midpoints between two consecutive points in the path

        Returns
        -------
        stepwise_path_energy : array-like, shape=[n_times-1]
            Stepwise path energy.
        """
        n_times = path.shape[0]
        print("n_times shape: " + str(n_times))
        diff = path[1:, :, :] - path[:-1, :, :]
        print("diff shape: " + str(diff.shape))
        midpoints = path[0 : n_times - 1, :, :] + diff / 2  # NOQA
        energy = []
        for i in range(0, n_times - 1):
            energy += [n_times * self.squared_norm(diff[i], midpoints[i])]
        return gs.array(energy)

    def path_energy(self, path):
        """Compute path energy of a PL path in the space of discrete surfaces.

        Parameters
        ----------
        path: array-like, shape=[n_times, n_vertices, 3]
            PL path of discrete surfaces.

        Returns
        -------
        path_energy : float
            total path energy.
        """
        return 0.5 * gs.sum(self.stepwise_path_energy(path))

    def geodesic(self, initial_point, end_point=None, initial_tangent_vec=None):
        """Compute a geodesic.

        Given an initial point and either an endpoint or initial vector.

        Parameters
        ----------
        initial_point: array-like, shape=[n_vertices, 3]
            Initial discrete surface
        end_point: array-like, shape=[n_vertices, 3]
            End discrete surface: endpoint for the boundary value geodesic problem
            Optional, default: None.
        initial_tangent_vec: array-like, shape=[n_vertices, 3]
            Initial tangent vector
            Optional, default: None.

        Returns
        -------
        path_energy : float
            total path energy.
        """
        if end_point is not None:
            return self._bvp(initial_point, end_point)
        if initial_tangent_vec is not None:
            return self._ivp(initial_point, initial_tangent_vec)

    def exp(self, tangent_vec, base_point):
        """Compute exponential map associated to the Riemmannian metric.

        Exponential map at base_point of tangent_vec computed
        by discrete geodesic calculus methods.

        Parameters
        ----------
        tangent_vec : array-like, shape=[n_vertices, 3]
            Tangent vector at the base point.
        base_point : array-like, shape=[n_vertices, 3]
            Point on the manifold.

        Returns
        -------
        exp : array-like, shape=[nv,3]
            Point on the manifold.
        """
        geod = self._ivp(base_point, tangent_vec)
        return geod[-1]

    def log(self, point, base_point):
        """Compute logarithm map associated to the Riemannian metric.

        Solve the boundary value problem associated to the geodesic equation
        using path straightening.

        Parameters
        ----------
        point : array-like, shape=[n_vertices,3]
            Point on the manifold.
        base_point : array-like, shape=[n_vertices,3]
            Point on the manifold.

        Returns
        -------
        tangent_vec : array-like, shape=[n_vertices,3]
            Tangent vector at the base point.
        """
        geod = self._bvp(base_point, point)
        return geod[1] - geod[0]

    def _bvp(self, initial_point, end_point):
        n_points = initial_point.shape[0]
        step = (end_point - initial_point) / (self.n_times - 1)
        # create a straight line between initial and end points for initialization
        geod = gs.array([initial_point + i * step for i in range(0, self.n_times)])
        midpoints = geod[1 : self.n_times - 1]  # NOQA
        print("geodesic shape" + str(midpoints.shape))
        print("flattened geodesic shape" + str(gs.flatten(midpoints).shape))

        self.remove_degenerate_faces(midpoints, n_points)

        # needs to be differentiable with respect to midpoints
        def funopt(midpoint):
            midpoint = gs.reshape(gs.array(midpoint), (self.n_times - 2, n_points, 3))
            print("midpoint shape" + str(midpoint.shape))
            print(len(midpoint))

            self.remove_degenerate_faces(midpoint, n_points)

            return self.path_energy(
                gs.concatenate(
                    [initial_point[None, :, :], midpoint, end_point[None, :, :]], axis=0
                )
            )

        # find midpoints that minimize path energy
        sol = minimize(
            gs.autodiff.value_and_grad(funopt, to_numpy=True),
            gs.flatten(midpoints),
            method="L-BFGS-B",
            jac=True,
            options={"disp": True, "ftol": 0.001},
        )
        out = gs.reshape(gs.array(sol.x), (self.n_times - 2, n_points, 3))
        geod = gs.concatenate(
            [initial_point[None, :, :], out, end_point[None, :, :]], axis=0
        )
        return geod

    def _ivp(self, initial_point, initial_tangent_vec):
        initial_tangent_vec = initial_tangent_vec / (self.n_times - 1)
        vertex_0 = initial_point
        vertex_1 = vertex_0 + initial_tangent_vec
        ivp = [vertex_0, vertex_1]
        for i in range(2, self.n_times):
            vertex_2 = self._stepforward(vertex_0, vertex_1)
            ivp += [vertex_2]
            vertex_0 = vertex_1
            vertex_1 = vertex_2
        return gs.stack(ivp, axis=0)

    def _stepforward(self, vertex_0, vertex_1):
        n_points = vertex_0.shape[0]
        B = gs.zeros([n_points, 3]).requires_grad_(True)
        qV1 = vertex_1.clone().requires_grad_(True)

        def energy(vertex_2):
            edge_10 = vertex_1 - vertex_0
            edge_21 = vertex_2 - vertex_1

            def get_inner_product_1(Vdot):
                return self.inner_product(edge_10, Vdot, vertex_0)

            def get_inner_product_2(Vdot):
                return self.inner_product(edge_21, Vdot, vertex_1)

            def norm(vertex_1):
                return self.squared_norm(edge_21, vertex_1)

            sys1 = grad(get_inner_product_1(B), B, create_graph=True)[0]
            sys2 = grad(get_inner_product_2(B), B, create_graph=True)[0]
            sys3 = grad(norm(qV1), qV1, create_graph=True)[0]

            sys = 2 * sys1 - 2 * sys2 + sys3
            return gs.sum(sys**2)

        def funopt(vertex_2):
            vertex_2 = gs.reshape(gs.array(vertex_2), (n_points, 3))
            return energy(vertex_2)

        sol = minimize(
            gs.autodiff.value_and_grad(funopt),
            gs.flatten(2 * (vertex_1 - vertex_0) + vertex_0),
            method="L-BFGS-B",
            jac=True,
            options={"disp": True, "ftol": 0.00001},
        )
        return gs.reshape(gs.array(sol.x), (n_points, 3))

    def dist(self, point_a, point_b):
        """Compute geodesic distance between two discrete surfaces.

        Parameters
        ----------
        point_a : array-like, shape=[n_vertices,3]
            Point.
        point_b : array-like, shape=[n_vertices,3]
            Point.

        Returns
        -------
        dist : float
            Distance.
        """
        geod = self._bvp(point_a, point_b)
        energy = self.stepwise_path_energy(geod)
        return gs.sum(gs.sqrt(energy))

    def remove_degenerate_faces(self, vertices_list, n_points):
        """
        Remove degenerate faces from a list of vertices
        """
        midpoint = vertices_list
        for i_mesh in range(len(midpoint)):
            point = midpoint[i_mesh]
            print("2D point array" + str(point.shape))
            point = torch.Tensor(point).detach().numpy()
            # point = torch.Tensor(point)
            area_threshold = 0.01
            mesh = trimesh.Trimesh(point, self.space.faces)
            # make sure that the midpoints don't have degenerate faces
            face_areas = self.space.face_areas(point)
            face_mask = ~gs.less(face_areas, area_threshold)
            mesh.update_faces(face_mask)
            vertices = torch.Tensor(mesh.vertices)
            if i_mesh == 0:
                nondegenerate_meshes = vertices
            else:
                nondegenerate_meshes = gs.concatenate(
                    [nondegenerate_meshes, vertices], axis=0
                )
        midpoint = nondegenerate_meshes
        midpoint = gs.reshape(gs.array(midpoint), (self.n_times - 2, n_points, 3))
        print("nondegenerate midpoint shape" + str(midpoint.shape))
        return midpoint
