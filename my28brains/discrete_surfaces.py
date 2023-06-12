"""Discrete Surfaces with Elastic metrics.

Lead authors: Emmanuel Hartman, Adele Myers.
"""
import math

import geomstats.backend as gs
import numpy as np
import torch
from geomstats.geometry.euclidean import Euclidean
from geomstats.geometry.manifold import Manifold
from geomstats.geometry.riemannian_metric import RiemannianMetric
from scipy.optimize import minimize
from torch.autograd import grad

N_STEPS = 10


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
        Triangulation of the surface.
        Each face is given by 3 indices that indicate its vertices.
    """

    def __init__(self, faces):
        ambient_dim = 3
        self.ambient_manifold = Euclidean(dim=ambient_dim)
        self.faces = gs.array(faces)
        self.n_faces = len(faces)
        self.n_vertices = int(gs.amax(self.faces) + 1)
        self.shape = (self.n_vertices, ambient_dim)
        super().__init__(
            dim=self.n_vertices * ambient_dim,
            shape=(self.n_vertices, 3),
            equip=False,
        )

    def belongs(self, point, atol=gs.atol):
        """Evaluate whether a point belongs to the manifold.

        Checks that vertices are inputed in proper form and are
        consistent with the mesh structure.

        Parameters
        ----------
        point : array-like, shape=[..., n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.
        atol : float
            Absolute tolerance.
            Optional, default: backend atol.

        Returns
        -------
        belongs : array-like, shape=[...,]
            Boolean evaluating if point belongs to the space of discrete
            surfaces.
        """
        belongs = self.shape == point.shape[-self.point_ndim :]
        shape = point.shape[: -self.point_ndim]
        if belongs:
            return gs.ones(shape, dtype=bool)
        return gs.zeros(shape, dtype=bool)

    def is_tangent(self, vector, base_point, atol=gs.atol):
        """Check whether the vector is tangent at base_point.

        Tangent vectors are identified with points of the vector space so
        this checks the shape of the input vector.

        Parameters
        ----------
        vector : array-like, shape=[..., n_vertices, 3]
            Vector, i.e. a 3D vector field on the surface.
        base_point : array-like, shape=[..., n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.
        atol : float
            Absolute tolerance.
            Optional, default: backend atol.

        Returns
        -------
        is_tangent : array-like, shape=[...,]
            Boolean denoting if vector is a tangent vector at the base point.
        """
        belongs = self.belongs(vector, atol)
        if base_point is not None and base_point.ndim > vector.ndim:
            return gs.broadcast_to(belongs, base_point.shape[: -self.point_ndim])
        return belongs

    def to_tangent(self, vector, base_point):
        """Project a vector to a tangent space of the manifold.

        Parameters
        ----------
        vector : array-like, shape=[..., n_vertices, 3]
            Vector, i.e. a 3D vector field on the surface.
        base_point : array-like, shape=[..., n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        tangent_vec : array-like, shape=[..., *point_shape]
            Tangent vector at base point.
        """
        return gs.copy(vector)

    def projection(self, point):
        """Project a point to the manifold.

        Parameters
        ----------
        point : array-like, shape=[..., n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation..

        Returns
        -------
        _ : array-like, shape=[..., n_vertices, 3]
            Point.
        """
        return gs.copy(point)

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
        vertices : array-like, shape=[n_samples, n_vertices, 3]
            Vertices for a batch of points in the space of discrete surfaces.
        """
        vertices = self.ambient_manifold.random_point(n_samples * self.n_vertices)
        vertices = gs.reshape(vertices, (n_samples, self.n_vertices, 3))
        return vertices[0] if n_samples == 1 else vertices

    def _vertices(self, point):
        """Extract 3D vertices coordinates corresponding to each face.

        Parameters
        ----------
        point : array-like, shape=[..., n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        vertices : tuple of vertex_0, vertex_1, vertex_2 where:
            vertex_i : array-like, shape=[..., n_faces, 3]
                3D coordinates of the ith vertex of that face.
        """
        vertex_0, vertex_1, vertex_2 = tuple(
            gs.take(point, indices=self.faces[:, i], axis=-2) for i in range(3)
        )
        if point.ndim == 3 and vertex_0.ndim == 2:
            vertex_0 = gs.expand_dims(vertex_0, axis=0)
            vertex_1 = gs.expand_dims(vertex_1, axis=0)
            vertex_2 = gs.expand_dims(vertex_2, axis=0)
        return vertex_0, vertex_1, vertex_2

    def _triangle_areas(self, point):
        """Compute triangle areas for each face of the surface.

        Heron's formula gives the triangle's area in terms of its sides a b c:,
        As the square root of the product s(s - a)(s - b)(s - c),
        where s is the semiperimeter of the triangle s = (a + b + c)/2.

        Parameters
        ----------
        point : array-like, shape=[..., n_vertices, 3]
             Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        _ : array-like, shape=[..., n_faces, 1]
            Triangle area of each face.
        """
        vertex_0, vertex_1, vertex_2 = self._vertices(point)
        len_edge_12 = gs.linalg.norm((vertex_1 - vertex_2), axis=-1)
        len_edge_02 = gs.linalg.norm((vertex_0 - vertex_2), axis=-1)
        len_edge_01 = gs.linalg.norm((vertex_0 - vertex_1), axis=-1)
        half_perimeter = 0.5 * (len_edge_12 + len_edge_02 + len_edge_01)
        return gs.sqrt(
            (
                half_perimeter
                * (half_perimeter - len_edge_12)
                * (half_perimeter - len_edge_02)
                * (half_perimeter - len_edge_01)
            ).clip(min=1e-6)
        )

    def vertex_areas(self, point):
        """Compute vertex areas for a triangulated surface.

        Vertex area is the area of all of the triangles who are in contact (incident)
        with a specific vertex, according to the formula:
        vertex_areas = 2 * sum_incident_areas / 3.0

        Parameters
        ----------
        point : array-like, shape=[..., n_vertices, 3]
             Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        vertex_areas :  array-like, shape=[..., n_vertices, 1]
            Vertex area for each vertex.
        """
        batch_shape = point.shape[:-2]
        n_vertices = point.shape[-2]
        n_faces = self.faces.shape[0]
        area = self._triangle_areas(point)
        id_vertices = gs.broadcast_to(
            gs.flatten(gs.array(self.faces)),
            batch_shape + (math.prod(self.faces.shape),),
        )
        incident_areas = gs.zeros(batch_shape + (n_vertices,))
        val = gs.reshape(
            gs.broadcast_to(gs.expand_dims(area, axis=-2), batch_shape + (3, n_faces)),
            batch_shape + (-1,),
        )
        incident_areas = gs.scatter_add(
            incident_areas, dim=len(batch_shape), index=id_vertices, src=val
        )
        vertex_areas = 2 * incident_areas / 3.0
        return vertex_areas

    def normals(self, point):
        """Compute normals at each face of a triangulated surface.

        Normals are the cross products between edges of each face
        that are incident to its x-coordinate.

        Parameters
        ----------
        point : array-like, shape=[n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        normals_at_point : array-like, shape=[n_faces, 3]
            Normals of each face of the mesh.
        """
        vertex_0, vertex_1, vertex_2 = self._vertices(point)
        normals_at_point = 0.5 * gs.cross(vertex_1 - vertex_0, vertex_2 - vertex_0)
        return normals_at_point

    def surface_one_forms(self, point):
        """Compute the vector valued one-forms.

        The one forms are evaluated at the faces of a triangulated surface.

        A one-form is represented by the two vectors (01) and (02) at each face
        of vertices 0, 1, 2.

        Parameters
        ----------
        point : array-like, shape=[..., n_vertices, 3]
             Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        one_forms_bp : array-like, shape=[..., n_faces, 2, 3]
            One form evaluated at each face of the triangulated surface.
        """
        vertex_0, vertex_1, vertex_2 = self._vertices(point)
        one_forms = gs.stack([vertex_1 - vertex_0, vertex_2 - vertex_0], axis=-2)
        return one_forms

    def face_areas(self, point):
        """Compute the areas for each face of a triangulated surface.

        The corresponds to the volume area for the surface metric, that is
        the volume area of the pullback metric of the immersion defining the
        surface metric.

        Parameters
        ----------
        point : array-like, shape=[n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        _ : array-like, shape=[n_faces,]
            Area computed at each face of the triangulated surface.
        """
        surface_metrics_bp = self.surface_metric_matrices(point)
        return gs.sqrt(gs.linalg.det(surface_metrics_bp))

    @staticmethod
    def _surface_metric_matrices_from_one_forms(one_forms):
        """Compute the surface metric matrices directly from the one_forms.

        This function is useful for efficiency purposes.

        Parameters
        ----------
        one_forms : array-like, shape=[..., n_faces, 2, 3]
            One form evaluated at each face of the triangulated surface.

        Returns
        -------
        metric_mats : array-like, shape=[n_faces, 2, 2]
            Surface metric matrices evaluated at each face of
            the triangulated surface.
        """
        ndim = one_forms.ndim
        transpose_axes = tuple(range(ndim - 2)) + tuple(reversed(range(ndim - 2, ndim)))
        transposed_one_forms = gs.transpose(one_forms, axes=transpose_axes)
        return gs.matmul(one_forms, transposed_one_forms)

    def surface_metric_matrices(self, point):
        """Compute the surface metric matrices.

        The matrices are evaluated at the faces of a triangulated surface.

        The surface metric is the pullback metric of the immersion q
        defining the surface, i.e. of
        the map q: M -> R3, where M is the parameterization manifold.

        Parameters
        ----------
        point : array like, shape=[n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        metric_mats : array-like, shape=[n_faces, 2, 2]
            Surface metric matrices evaluated at each face of
            the triangulated surface.
        """
        one_forms = self.surface_one_forms(point)

        return self._surface_metric_matrices_from_one_forms(one_forms)

    def laplacian(self, point):
        r"""Compute the mesh Laplacian operator of a triangulated surface.

        Denoting q the surface, i.e. the point in the DiscreteSurfaces manifold,
        the laplacian at q is defined as the operator:
        :math: `\Delta_q = - Tr(g_q^{-1} \nabla^2)`
        where :math:`g_q` is the surface metric matrix of :math:`q`.

        Parameters
        ----------
        point :  array-like, shape=[n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        _laplacian : callable
            Function that evaluates the mesh Laplacian operator at a
            tangent vector field to the surface.
        """
        n_vertices, n_faces = point.shape[-2], self.faces.shape[0]
        vertex_0, vertex_1, vertex_2 = self._vertices(point)
        len_edge_12 = gs.linalg.norm((vertex_1 - vertex_2), axis=-1)
        len_edge_02 = gs.linalg.norm((vertex_0 - vertex_2), axis=-1)
        len_edge_01 = gs.linalg.norm((vertex_0 - vertex_1), axis=-1)

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
        id_vertices_120 = self.faces[:, [1, 2, 0]]
        id_vertices_201 = self.faces[:, [2, 0, 1]]
        id_vertices = gs.reshape(
            gs.stack([id_vertices_120, id_vertices_201], axis=0), (2, n_faces * 3)
        )

        def _laplacian(tangent_vec):
            """Evaluate the mesh Laplacian operator.

            The operator is evaluated at a tangent vector at point to the
            manifold of DiscreteSurfaces. In other words, the operator is
            evaluated at a vector field defined on the surface point.

            Parameters
            ----------
            tangent_vec : array-like, shape=[..., n_vertices, 3]
                Tangent vector to the manifold at the base point that is the
                triangulated surface. This tangent vector is a vector field
                on the triangulated surface.

            Returns
            -------
            laplacian_at_tangent_vec: array-like, shape=[..., n_vertices, 3]
                Mesh Laplacian operator of the triangulated surface applied
                to one its tangent vector tangent_vec.
            """
            to_squeeze = False
            if tangent_vec.ndim == 2:
                tangent_vec = gs.expand_dims(tangent_vec, axis=0)
                to_squeeze = True
            n_tangent_vecs = len(tangent_vec)
            tangent_vec_diff = (
                tangent_vec[:, id_vertices[0]] - tangent_vec[:, id_vertices[1]]
            )
            values = gs.einsum(
                "bd,nbd->nbd", gs.stack([gs.flatten(cot)] * 3, axis=1), tangent_vec_diff
            )

            laplacian_at_tangent_vec = gs.zeros((n_tangent_vecs, n_vertices, 3))

            id_vertices_201_repeated = gs.tile(id_vertices[1, :], (n_tangent_vecs, 1))

            for i_dim in range(3):
                laplacian_at_tangent_vec[:, :, i_dim] = gs.scatter_add(
                    input=laplacian_at_tangent_vec[:, :, i_dim],
                    dim=1,
                    index=id_vertices_201_repeated,
                    src=values[:, :, i_dim],
                )
            return (
                gs.squeeze(laplacian_at_tangent_vec, axis=0)
                if to_squeeze
                else laplacian_at_tangent_vec
            )

        return _laplacian


class ElasticMetric(RiemannianMetric):
    """Elastic metric defined by a family of second order Sobolev metrics.

    Each individual discrete surface is represented by a 2D-array of shape `[
    n_vertices, 3]`. See [HSKCB2022]_ for details.

    The parameters a0, a1, b1, c1, d1, a2 (detailed below) are non-negative weighting
    coefficients for the different terms in the metric.

    Parameters
    ----------
    space : DiscreteSurfaces
        Instantiated DiscreteSurfaces manifold.
    a0 : float
        First order parameter.
        Default: 1.
    a1 : float
        Stretching parameter.
        Default: 1.
    b1 : float
        Shearing parameter.
        Default: 1.
    c1 : float
        Bending parameter.
        Default: 1.
    d1 : float
        Additonal first order parameter.
        Default: 1.
    a2 : float
        Second order parameter.
        Default: 1.

    References
    ----------
    .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
        Sobolev metrics: a comprehensive numerical framework".
        arXiv:2204.04238 [cs.CV], 25 Sep 2022
    """

    def __init__(self, space, a0=1.0, a1=1.0, b1=1.0, c1=1.0, d1=1.0, a2=1.0):
        super().__init__(space=space)
        self.a0 = a0
        self.a1 = a1
        self.b1 = b1
        self.c1 = c1
        self.d1 = d1
        self.a2 = a2

    def _inner_product_a0(self, tangent_vec_a, tangent_vec_b, vertex_areas_bp):
        r"""Compute term of order 0 within the inner-product.

        Denote h and k the tangent vectors a and b respectively.
        Denote q the base point, i.e. the surface.

        The equation of the inner-product is:
        :math:`\int_M (G_{a_0} + G_{a_1} + G_{b_1} + G_{c_1} + G_{d_1} + G_{a_2})vol_q`.

        This method computes :math:`G_{a_0} = a_0 <h, k>`,
        with notations taken from .. [HSKCB2022].

        Parameters
        ----------
        tangent_vec_a : array-like, shape=[..., n_vertices, 3]
            Tangent vector at base point.
        tangent_vec_b : array-like, shape=[..., n_vertices, 3]
            Tangent vector at base point.
        vertex_areas : array-like, shape=[n_vertices, 3]
            Vertex areas for each vertex of the base_point.

        Returns
        -------
        _ : array-like, shape=[...]
            Term of order 0, and coefficient a0, of the inner-product.

        References
        ----------
        .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
            Sobolev metrics: a comprehensive numerical framework".
            arXiv:2204.04238 [cs.CV], 25 Sep 2022.
        """
        return self.a0 * gs.sum(
            vertex_areas_bp
            * gs.einsum("...bi,...bi->...b", tangent_vec_a, tangent_vec_b),
            axis=-1,
        )

    def _inner_product_a1(self, ginvdga, ginvdgb, areas_bp):
        r"""Compute a1 term of order 1 within the inner-product.

        Denote h and k the tangent vectors a and b respectively.
        Denote q the base point, i.e. the surface.

        The equation of the inner-product is:
        :math:`\int_M (G_{a_0} + G_{a_1} + G_{b_1} + G_{c_1} + G_{d_1} + G_{a_2})vol_q`.

        This method computes :math:`G_{a_1} = a_1.g_q^{-1} <dh_m, dk_m>`,
        with notations taken from .. [HSKCB2022].

        Parameters
        ----------
        ginvdga : array-like, shape=[n_faces, 2, 2]
            Product of the inverse of the surface metric matrices
            with their differential at a.
        ginvdgb : array-like, shape=[n_faces, 2, 2]
            Product of the inverse of the surface metric matrices
            with their differential at b.
        areas_bp : array-like, shape=[n_faces,]
            Areas of the faces of the surface given by the base point.

        Returns
        -------
        _ : array-like, shape=[...]
            Term of order 0, and coefficient a1, of the inner-product.

        References
        ----------
        .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
            Sobolev metrics: a comprehensive numerical framework".
            arXiv:2204.04238 [cs.CV], 25 Sep 2022.
        """
        return self.a1 * gs.sum(
            gs.einsum("...bii->...b", gs.matmul(ginvdga, ginvdgb)) * areas_bp,
            axis=-1,
        )

    def _inner_product_b1(self, ginvdga, ginvdgb, areas_bp):
        r"""Compute b1 term of order 1 within the inner-product.

        Denote h and k the tangent vectors a and b respectively.
        Denote q the base point, i.e. the surface.

        The equation of the inner-product is:
        :math:`\int_M (G_{a_0} + G_{a_1} + G_{b_1} + G_{c_1} + G_{d_1} + G_{a_2})vol_q`.

        This method computes :math:`G_{b_1} = b_1.g_q^{-1} <dh_+, dk_+>`,
        with notations taken from .. [HSKCB2022].

        Parameters
        ----------
        ginvdga : array-like, shape=[n_faces, 2, 2]
            Product of the inverse of the surface metric matrices
            with their differential at a.
        ginvdgb : array-like, shape=[n_faces, 2, 2]
            Product of the inverse of the surface metric matrices
            with their differential at b.
        areas_bp : array-like, shape=[n_faces,]
            Areas of the faces of the surface given by the base point.

        Returns
        -------
        _ : array-like, shape=[...]
            Term of order 0, and coefficient b1, of the inner-product.

        References
        ----------
        .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
            Sobolev metrics: a comprehensive numerical framework".
            arXiv:2204.04238 [cs.CV], 25 Sep 2022.
        """
        return self.b1 * gs.sum(
            gs.einsum("...bii->...b", ginvdga)
            * gs.einsum("...bii->...b", ginvdgb)
            * areas_bp,
            axis=-1,
        )

    def _inner_product_c1(self, point_a, point_b, normals_bp, areas_bp):
        r"""Compute c1 term of order 1 within the inner-product.

        Denote h and k the tangent vectors a and b respectively.
        Denote q the base point, i.e. the surface.

        The equation of the inner-product is:
        :math:`\int_M (G_{a_0} + G_{a_1} + G_{b_1} + G_{c_1} + G_{d_1} + G_{a_2})vol_q`.

        This method computes :math:`G_{c_1} = c_1.g_q^{-1} <dh_\perp, dk_\perp>`,
        with notations taken from .. [HSKCB2022].

        Parameters
        ----------
        point_a : array-like, shape=[..., n_vertices, 3]
            Point a corresponding to tangent vec a.
        point_b : array-like, shape=[..., n_vertices, 3]
            Point b corresponding to tangent vec b.
        normals_bp : array-like, shape=[n_faces, 3]
            Normals of each face of the surface given by the base point.
        areas_bp : array-like, shape=[n_faces,]
            Areas of the faces of the surface given by the base point.

        Returns
        -------
        _ : array-like, shape=[...]
            Term of order 0, and coefficient c1, of the inner-product.

        References
        ----------
        .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
            Sobolev metrics: a comprehensive numerical framework".
            arXiv:2204.04238 [cs.CV], 25 Sep 2022.
        """
        dna = self._space.normals(point_a) - normals_bp
        dnb = self._space.normals(point_b) - normals_bp
        return self.c1 * gs.sum(
            gs.einsum("...bi,...bi->...b", dna, dnb) * areas_bp, axis=-1
        )

    def _inner_product_d1(
        self, one_forms_a, one_forms_b, one_forms_bp, areas_bp, inv_surface_metrics_bp
    ):
        r"""Compute d1 term of order 1 within the inner-product.

        Denote h and k the tangent vectors a and b respectively.
        Denote q the base point, i.e. the surface.

        The equation of the inner-product is:
        :math:`\int_M (G_{a_0} + G_{a_1} + G_{b_1} + G_{c_1} + G_{d_1} + G_{a_2})vol_q`.

        This method computes :math:`G_{d_1} = d_1.g_q^{-1} <dh_0, dk_0>`,
        with notations taken from .. [HSKCB2022].

        Parameters
        ----------
        one_forms_a : array-like, shape=[n_points, n_faces, 2, 3]
            One forms at point a corresponding to tangent vec a.
        one_forms_b : array-like, shape=[n_points, n_faces, 2, 3]
            One forms at point b corresponding to tangent vec b.
        one_forms_bp : array-like, shape=[n_faces, 2, 3]
            One forms at base point.
        areas_bp : array-like, shape=[n_faces,]
            Areas of the faces of the surface given by the base point.
        inv_surface_metrics_bp : array-like, shape=[n_faces, 2, 2]
            Inverses of the surface metric matrices at each face.

        Returns
        -------
        _ : array-like, shape=[...]
            Term of order 0, and coefficient d1, of the inner-product.

        References
        ----------
        .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
            Sobolev metrics: a comprehensive numerical framework".
            arXiv:2204.04238 [cs.CV], 25 Sep 2022.
        """
        one_forms_bp_t = gs.transpose(one_forms_bp, (0, 2, 1))

        one_forms_a_t = gs.transpose(one_forms_a, (0, 1, 3, 2))
        xa = one_forms_a_t - one_forms_bp_t

        xa_0 = gs.matmul(
            gs.matmul(one_forms_bp_t, inv_surface_metrics_bp),
            gs.matmul(gs.transpose(xa, (0, 1, 3, 2)), one_forms_bp_t)
            - gs.matmul(one_forms_bp, xa),
        )

        one_forms_b_t = gs.transpose(one_forms_b, (0, 1, 3, 2))
        xb = one_forms_b_t - one_forms_bp_t
        xb_0 = gs.matmul(
            gs.matmul(one_forms_bp_t, inv_surface_metrics_bp),
            gs.matmul(gs.transpose(xb, (0, 1, 3, 2)), one_forms_bp_t)
            - gs.matmul(one_forms_bp, xb),
        )

        return self.d1 * gs.sum(
            gs.einsum(
                "...bii->...b",
                gs.matmul(
                    xa_0,
                    gs.matmul(
                        inv_surface_metrics_bp, gs.transpose(xb_0, axes=(0, 1, 3, 2))
                    ),
                ),
            )
            * areas_bp
        )

    def _inner_product_a2(
        self, tangent_vec_a, tangent_vec_b, base_point, vertex_areas_bp
    ):
        r"""Compute term of order 2 within the inner-product.

        Denote h and k the tangent vectors a and b respectively.
        Denote q the base point, i.e. the surface.

        The equation of the inner-product is:
        :math:`\int_M (G_{a_0} + G_{a_1} + G_{b_1} + G_{c_1} + G_{d_1} + G_{a_2})vol_q`.

        This method computes :math:`G_{a_2} = a_2 <\Delta_q h, \Delta_q k>`,
        with notations taken from .. [HSKCB2022].

        Parameters
        ----------
        tangent_vec_a : array-like, shape=[..., n_vertices, 3]
            Tangent vector at base point.
        tangent_vec_b : array-like, shape=[..., n_vertices, 3]
            Tangent vector at base point.
        base_point : array-like, shape=[n_vertices, 3]
            Base point, a surface i.e. the 3D coordinates of its vertices.
        vertex_areas_bp : array-like, shape=[n_vertices, 1]
            Vertex areas for each vertex of the base_point.

        Returns
        -------
        _ : array-like, shape=[...]
            Term of order 2, and coefficient a2, of the inner-product.

        References
        ----------
        .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
            Sobolev metrics: a comprehensive numerical framework".
            arXiv:2204.04238 [cs.CV], 25 Sep 2022.
        """
        laplacian_at_base_point = self._space.laplacian(base_point)
        return self.a2 * gs.sum(
            gs.einsum(
                "...bi,...bi->...b",
                laplacian_at_base_point(tangent_vec_a),
                laplacian_at_base_point(tangent_vec_b),
            )
            / vertex_areas_bp,
            axis=-1,
        )

    def inner_product(self, tangent_vec_a, tangent_vec_b, base_point):
        r"""Compute inner product between two tangent vectors at a base point.

        The inner-product has 6 terms, where each term corresponds to
        one of the 6 hyperparameters a0, a1, b1, c1, d1, a2.

        We denote h and k the tangent vectors a and b respectively.
        We denote q the base point, i.e. the surface.

        The six terms of the inner-product are given by:
        :math:`\int_M (G_{a_0} + G_{a_1} + G_{b_1} + G_{c_1} + G_{d_1} + G_{a_2})vol_q`

        where:
        - :math:`G_{a_0} = a_0 <h, k>`
        - :math:`G_{a_1} = a_1.g_q^{-1} <dh_m, dk_m>`
        - :math:`G_{b_1} = b_1.g_q^{-1} <dh_+, dk_+>`
        - :math:`G_{c_1} = c_1.g_q^{-1} <dh_\perp, dk_\perp>`
        - :math:`G_{d_1} = d_1.g_q^{-1} <dh_0, dk_0>`
        - :math:`G_{a_2} = a_2 <\Delta_q h, \Delta_q k>`

        with notations taken from .. [HSKCB2022].

        Parameters
        ----------
        tangent_vec_a : array-like, shape=[..., n_vertices, 3]
            Tangent vector at base point.
        tangent_vec_b : array-like, shape=[..., n_vertices, 3]
            Tangent vector at base point.
        base_point : array-like, shape=[n_vertices, 3]
            Surface, as the 3D coordinates of the vertices of its triangulation.

        Returns
        -------
        inner_prod : array-like, shape=[...]
            Inner-product.

        References
        ----------
        .. [HSKCB2022] "Elastic shape analysis of surfaces with second-order
            Sobolev metrics: a comprehensive numerical framework".
            arXiv:2204.04238 [cs.CV], 25 Sep 2022.
        """
        to_squeeze = False
        if tangent_vec_a.ndim == 2 and tangent_vec_b.ndim == 2:
            to_squeeze = True
        if tangent_vec_a.ndim == 2:
            tangent_vec_a = gs.expand_dims(tangent_vec_a, axis=0)
        if tangent_vec_b.ndim == 2:
            tangent_vec_b = gs.expand_dims(tangent_vec_b, axis=0)

        print(f"base_point.shape = {base_point.shape}")  # (n_vertices, 3)
        print(f"tangent_vec_a.shape = {tangent_vec_a.shape}")  # (1, n_vertices, 3)
        point_a = base_point + tangent_vec_a
        point_b = base_point + tangent_vec_b
        inner_prod = gs.zeros((gs.maximum(len(tangent_vec_a), len(tangent_vec_b)), 1))
        if self.a0 > 0 or self.a2 > 0:
            vertex_areas_bp = self._space.vertex_areas(base_point)
            if self.a0 > 0:
                inner_prod += self._inner_product_a0(
                    tangent_vec_a, tangent_vec_b, vertex_areas_bp=vertex_areas_bp
                )
            if self.a2 > 0:
                inner_prod += self._inner_product_a2(
                    tangent_vec_a,
                    tangent_vec_b,
                    base_point=base_point,
                    vertex_areas_bp=vertex_areas_bp,
                )
        if self.a1 > 0 or self.b1 > 0 or self.c1 > 0 or self.b1 > 0:
            one_forms_bp = self._space.surface_one_forms(base_point)
            surface_metrics_bp = self._space._surface_metric_matrices_from_one_forms(
                one_forms_bp
            )
            normals_bp = self._space.normals(base_point)
            areas_bp = gs.sqrt(gs.linalg.det(surface_metrics_bp))

            if self.c1 > 0:
                inner_prod += self._inner_product_c1(
                    point_a, point_b, normals_bp, areas_bp
                )
            if self.d1 > 0 or self.b1 > 0 or self.a1 > 0:
                ginv_bp = gs.linalg.inv(surface_metrics_bp)
                one_forms_a = self._space.surface_one_forms(point_a)
                one_forms_b = self._space.surface_one_forms(point_b)
                if self.d1 > 0:
                    inner_prod += self._inner_product_d1(
                        one_forms_a,
                        one_forms_b,
                        one_forms_bp,
                        areas_bp=areas_bp,
                        inv_surface_metrics_bp=ginv_bp,
                    )

                if self.b1 > 0 or self.a1 > 0:
                    dga = (
                        gs.matmul(
                            one_forms_a, gs.transpose(one_forms_a, axes=(0, 1, 3, 2))
                        )
                        - surface_metrics_bp
                    )
                    dgb = (
                        gs.matmul(
                            one_forms_b, gs.transpose(one_forms_b, axes=(0, 1, 3, 2))
                        )
                        - surface_metrics_bp
                    )
                    ginvdga = gs.matmul(ginv_bp, dga)
                    ginvdgb = gs.matmul(ginv_bp, dgb)
                    inner_prod += self._inner_product_a1(ginvdga, ginvdgb, areas_bp)
                    inner_prod += self._inner_product_b1(ginvdga, ginvdgb, areas_bp)
        return gs.squeeze(inner_prod, axis=0) if to_squeeze else inner_prod

    def path_energy_per_time(self, path):
        """Compute stepwise path energy of a path in the space of discrete surfaces.

        Parameters
        ----------
        path : array-like, shape=[..., n_times, n_vertices, 3]
            Piecewise linear path of discrete surfaces.

        Returns
        -------
        energy : array-like, shape=[..., n_times - 1,]
            Stepwise path energy.
        """
        need_squeeze = False
        if path.ndim == 3:
            path = gs.expand_dims(path, axis=0)
            need_squeeze = True
        n_times = path.shape[-3]
        surface_diffs = path[:, 1:, :, :] - path[:, :-1, :, :]
        surface_midpoints = path[:, : n_times - 1, :, :] + surface_diffs / 2
        energy_per_path = []
        for one_surface_diffs, one_surface_midpoints in zip(
            surface_diffs, surface_midpoints
        ):
            energy = []
            for diff, midpoint in zip(one_surface_diffs, one_surface_midpoints):
                energy.extend([n_times * self.squared_norm(diff, midpoint)])
            energy_per_path.append(gs.array(energy))
        energy_per_path = gs.array(energy_per_path)
        return gs.squeeze(energy_per_path, axis=0) if need_squeeze else energy_per_path

    def path_energy(self, path):
        """Compute path energy of a path in the space of discrete surfaces.

        Parameters
        ----------
        path : array-like, shape=[n_times, n_vertices, 3]
            Piecewise linear path of discrete surfaces.

        Returns
        -------
        energy : array-like, shape=[,]
            Path energy.
        """
        return 0.5 * gs.sum(self.path_energy_per_time(path))

    def _ivp(self, initial_point, initial_tangent_vec, times):
        """Solve initial value problem (IVP).

        Given an initial point and an initial vector, solve the geodesic equation.

        Parameters
        ----------
        initial_point : array-like, shape=[n_vertices, 3]
            Initial point, i.e. initial discrete surface.
        initial_tangent_vec : array-like, shape=[n_vertices, 3]
            Initial tangent vector.
        times : array-like, shape=[n_times,]
            Times between 0 and 1.

        Returns
        -------
        geod : array-like, shape=[n_times, n_vertices, 3]
            Geodesic discretized along the times given as inputs.
        """
        n_times = len(times)
        initial_tangent_vec = initial_tangent_vec / (n_times - 1)

        next_point = initial_point + initial_tangent_vec
        geod = [initial_point, next_point]
        for _ in range(2, n_times):
            next_next_point = self._stepforward(initial_point, next_point)
            geod += [next_next_point]
            initial_point = next_point
            next_point = next_next_point
        return gs.stack(geod, axis=0)

    def _stepforward(self, current_point, next_point):
        """Compute the next point on the geodesic.

        Parameters
        ----------
        current_point : array-like, shape=[n_vertices, 3]
            Current point on the geodesic.
        next_point : array-like, shape=[n_vertices, 3]
            Next point on the geodesic.

        Returns
        -------
        next_next_point : array-like, shape=[n_vertices, 3]
            Next next point on the geodesic.
        """
        current_point = gs.array(current_point)
        next_point = gs.array(next_point)
        n_vertices = current_point.shape[-2]
        zeros = gs.zeros([n_vertices, 3]).requires_grad_(True)
        next_point_clone = next_point.clone().requires_grad_(True)

        def energy_objective(next_next_point):
            """Compute the energy objective to minimize.

            Parameters
            ----------
            next_next_point : array-like, shape=[n_vertices, 3]
                Next next point on the geodesic.

            Returns
            -------
            energy_tot : array-like, shape=[,]
                Energy objective to minimize.
            """
            next_next_point = gs.reshape(gs.array(next_next_point), (n_vertices, 3))
            current_to_next = next_point - current_point
            next_to_next_next = next_next_point - next_point

            def _inner_product_with_current_to_next(tangent_vec):
                return self.inner_product(current_to_next, tangent_vec, current_point)

            def _inner_product_with_next_to_next_next(tangent_vec):
                return self.inner_product(next_to_next_next, tangent_vec, next_point)

            def _norm(base_point):
                return self.squared_norm(next_to_next_next, base_point)

            # _, energy_1 = gs.autodiff.value_and_grad(
            #     _inner_product_with_current_to_next
            # )(zeros)
            # _, energy_2 = gs.autodiff.value_and_grad(
            #     _inner_product_with_next_to_next_next
            # )(zeros)
            # _, energy_3 = gs.autodiff.value_and_grad(_norm)(next_point_clone)
            # energy_3 = energy_3.requires_grad_(True)

            energy_1 = grad(
                _inner_product_with_current_to_next(zeros),
                zeros,
                retain_graph=True,
                create_graph=True,
            )[0]
            energy_2 = grad(
                _inner_product_with_next_to_next_next(zeros),
                zeros,
                retain_graph=True,
                create_graph=True,
            )[0]
            energy_3 = grad(
                _norm(next_point_clone),
                next_point_clone,
                retain_graph=True,
                create_graph=True,
            )[0]

            energy_tot = 2 * energy_1 - 2 * energy_2 + energy_3
            return gs.sum(energy_tot**2)

        initial_next_next_point = gs.flatten(
            (2 * (next_point - current_point) + current_point)
        )

        sol = minimize(
            # gs.autodiff.value_and_grad(energy_objective, to_numpy=True),
            value_and_grad(energy_objective, to_numpy=True),
            initial_next_next_point.detach().numpy(),
            method="L-BFGS-B",
            jac=True,
            options={"disp": True, "ftol": 0.1},
        )
        return gs.reshape(gs.array(sol.x), (n_vertices, 3))

    def exp(self, tangent_vec, base_point, n_steps=N_STEPS, step=None):
        """Compute exponential map associated to the Riemmannian metric.

        Exponential map at base_point of tangent_vec computed
        by discrete geodesic calculus methods.

        Parameters
        ----------
        tangent_vec : array-like, shape=[n_vertices, 3]
            Tangent vector at the base point.
        base_point : array-like, shape=[n_vertices, 3]
            Point on the manifold.
        n_steps : int
            Number of time steps on the geodesic.

        Returns
        -------
        exp : array-like, shape=[n_vertices, 3]
            Point on the manifold.
        """
        exps = []
        need_squeeze = False
        times = gs.linspace(start=0.0, stop=1.0, num=n_steps)
        if tangent_vec.ndim == 2:
            tangent_vec = gs.expand_dims(tangent_vec, axis=0)
            need_squeeze = True
        for one_tangent_vec in tangent_vec:
            geod = self._ivp(base_point, one_tangent_vec, times=times)
            exps.append(geod[-1])
        exps = gs.array(exps)
        if need_squeeze:
            exps = gs.squeeze(exps, axis=0)
        return exps

    def log(self, point, base_point):
        """Compute logarithm map associated to the Riemannian metric.

        Solve the boundary value problem associated to the geodesic equation
        using path straightening.

        Parameters
        ----------
        point : array-like, shape=[..., n_vertices,3]
            Point on the manifold.
        base_point : array-like, shape=[n_vertices,3]
            Point on the manifold.

        Returns
        -------
        tangent_vec : array-like, shape=[..., n_vertices, 3]
            Tangent vector at the base point.
        """
        logs = []
        need_squeeze = False
        times = gs.linspace(0.0, 1.0, N_STEPS)

        if point.ndim == 2:
            point = gs.expand_dims(point, axis=0)
            need_squeeze = True
        if base_point.ndim == 2:
            base_point = gs.expand_dims(base_point, axis=0)
            need_squeeze = True
        for one_point in point:
            for one_base_point in base_point:
                geod = self._bvp(one_base_point, one_point, times)
                logs.append(geod[1] - geod[0])
        logs = gs.array(logs)
        if need_squeeze:
            logs = gs.squeeze(logs, axis=0)
        return logs

    def _bvp(self, initial_point, end_point, times):
        """Solve boundary value problem (IVP).

        Given an initial point and an end point, solve the geodesic equation.

        Parameters
        ----------
        initial_point : array-like, shape=[n_vertices, 3]
            Initial point, i.e. initial discrete surface.
        end_point : array-like, shape=[n_vertices, 3]
            End point, i.e. end discrete surface.
        times : array-like, shape=[n_times,]
            Times between 0 and 1.

        Returns
        -------
        geod : array-like, shape=[n_times, n_vertices, 3]
            Geodesic discretized on the times given as inputs.
        """
        n_points = initial_point.shape[-2]
        step = (end_point - initial_point) / (len(times) - 1)
        geod = gs.array([initial_point + i * step for i in times])
        midpoints = geod[1 : len(times) - 1]

        all_need_squeeze = False
        if midpoints.ndim == 3:
            all_need_squeeze = True
            initial_point = gs.expand_dims(initial_point, axis=0)
            end_point = gs.expand_dims(end_point, axis=0)
            midpoints = gs.expand_dims(midpoints, axis=0)
            num_points = midpoints.shape[0]
        else:
            if initial_point.ndim == 2:
                initial_point = gs.expand_dims(initial_point, axis=0)
                num_points = end_point.shape[0]
            if end_point.ndim == 2:
                end_point = gs.expand_dims(end_point, axis=0)
                num_points = initial_point.shape[0]
            midpoints = gs.reshape(
                midpoints, (num_points, self.n_times - 2, n_points, 3)
            )

        def objective(midpoint):
            """Compute path energy of paths going through a midpoint.

            Parameters
            ----------
            midpoint : array-like, shape=[..., n_vertices, 3]
                Midpoint of the path, i.e. a discrete surface.

            Returns
            -------
            _ : array-like, shape=[...]
                Energy of the path going through this midpoint.
            """
            midpoint = gs.reshape(
                gs.array(midpoint), (num_points, len(times) - 2, n_points, 3)
            )

            paths = []
            for one_midpoint, one_initial_point, one_end_point in zip(
                midpoint, initial_point, end_point
            ):
                one_path = gs.concatenate(
                    [
                        one_initial_point[None, :, :],
                        one_midpoint,
                        one_end_point[None, :, :],
                    ],
                    axis=0,
                )
                paths.append(one_path)
            paths = gs.array(paths)
            return self.path_energy(paths)

        initial_geod = gs.flatten(midpoints)

        sol = minimize(
            # gs.autodiff.value_and_grad(objective, to_numpy=True),
            value_and_grad(objective, to_numpy=True),
            initial_geod.detach().numpy(),
            method="L-BFGS-B",
            jac=True,
            options={"disp": True, "ftol": 1},
        )
        out = gs.reshape(gs.array(sol.x), (num_points, len(times) - 2, n_points, 3))

        geod = []
        for one_out, one_initial_point, one_end_point in zip(
            out, initial_point, end_point
        ):
            one_geod = gs.concatenate(
                [one_initial_point[None, :, :], one_out, one_end_point[None, :, :]],
                axis=0,
            )
            geod.append(one_geod)
        geod = gs.array(geod)
        if all_need_squeeze:
            geod = gs.squeeze(geod, axis=0)

        return geod


def value_and_grad(func, argnums=0, to_numpy=False):
    """Return a function that returns func's value and gradients' values.

    Suitable for use in scipy.optimize with to_numpy=True.

    Parameters
    ----------
    func : callable
        Function whose value and gradient values
        will be computed. It must be real-valued.
    to_numpy : bool
        Determines if the outputs value and grad will be cast
        to numpy arrays. Set to "True" when using scipy.optimize.
        Optional, default: False.

    Returns
    -------
    func_with_grad : callable
        Function that returns func's value and
        func's gradients' values at its inputs args.
    """
    if isinstance(argnums, int):
        argnums = (argnums,)

    def func_with_grad(*args, **kwargs):
        """Return func's value and func's gradients' values at args.

        Parameters
        ----------
        args : list
            Argument to function func and its gradients.
        kwargs : dict
            Keyword arguments to function func and its gradients.

        Returns
        -------
        value : any
            Value of func at input arguments args.
        all_grads : list or any
            Values of func's gradients at input arguments args.
        """
        new_args = []
        for i_arg, one_arg in enumerate(args):
            if isinstance(one_arg, float):
                # one_arg = _torch.from_numpy(_np.array(one_arg))
                one_arg = torch.from_numpy(np.array(one_arg))
            # if isinstance(one_arg, _np.ndarray):
            #     one_arg = _torch.from_numpy(one_arg)
            if isinstance(one_arg, np.ndarray):
                one_arg = torch.from_numpy(one_arg)

            requires_grad = i_arg in argnums
            one_arg = one_arg.detach().requires_grad_(requires_grad)
            new_args.append(one_arg)

        value = func(*new_args, **kwargs)

        if value.ndim > 0:
            sum_value = value.sum()
            sum_value.backward(retain_graph=True)
        else:
            value.backward(retain_graph=True)

        all_grads = []
        for i_arg, one_arg in enumerate(new_args):
            if i_arg in argnums:
                all_grads.append(
                    one_arg.grad,
                )

        if to_numpy:
            value = value.detach().numpy()
            all_grads = [one_grad.detach().numpy() for one_grad in all_grads]

        if len(new_args) == 1:
            return value, all_grads[0]
        return value, tuple(all_grads)

    return func_with_grad
