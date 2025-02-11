import time

import torch
import math

import silearn.model.encoding_tree
from silearn.optimizer.enc.operator import Operator
# import torch_sparse


import ctypes

import os
import numpy as np
import torch
import torch.nn.functional as F
def pairwise_cos_sim(x1: torch.Tensor, x2: torch.Tensor):
    """
    return pair-wise similarity matrix between two tensors
    :param x1: [B,...,M,D]
    :param x2: [B,...,N,D]
    :return: similarity matrix [B,...,M,N]
    """
    x1 = F.normalize(x1, dim=-1)
    x2 = F.normalize(x2, dim=-1)

    sim = torch.matmul(x1, x2.transpose(-2, -1))
    return sim

class OperatorPropagation(Operator):
    # partition: silearn.model.enc.encoding_tree.Partitioning
    adjacency_restriction: None

    @staticmethod
    def reduction_edge(edges, edge_transform, *weights):
        cnt_e = edge_transform.max() + 1
        e1 = torch.zeros(size=(cnt_e, edges.shape[1]), dtype=edges.dtype, device=edges.device)
        # print(edge_transform.shape)
        # print(edges.shape)
        # print(e1.shape)
        edges = e1.scatter(0, edge_transform.reshape(-1, 1).repeat((1,2)), edges)
        ret = [edges] + [silearn.scatter_sum(w, edge_transform) for w in weights]
        return tuple(ret)

    @staticmethod
    def get_edge_transform(edges, identical_flag=False):
        max_id = int(edges[:, 1].max() + 1)
        bd = 1
        shift = 0
        while bd <= max_id:
            bd = bd << 1
            shift += 1
        # todo: hash if shift is too big
        edge_hash = (edges[:, 0] << shift) + edges[:, 1]


        if identical_flag:
            _, transform, counts = torch.unique(edge_hash, return_inverse=True, return_counts=True)
            flag = counts[transform] != 1
            return transform, flag
        else:
            _, transform = torch.unique(edge_hash, return_inverse=True)
            return transform

    @staticmethod
    def sum_up_multi_edge(edges, *weights, operation_ptrs=None):
        if operation_ptrs is not None:
            em = edges[operation_ptrs]
            wm = [i[operation_ptrs] for i in weights]
            trans = OperatorPropagation.get_edge_transform(em)
            redu = OperatorPropagation.reduction_edge(em, trans, *wm)
            cnt = redu[0].shape[0]
            # operation_ptrs = operation_ptrs[:cnt]
            # skip_ptrs = operation_ptrs[cnt:]
            # edges[operation_ptrs] = 0
            edges[operation_ptrs][:cnt] = redu[0]
            ret = [edges]
            for i in range(len(weights)):
                weights[i][operation_ptrs][:cnt] = redu[i + 1]
                weights[i][operation_ptrs][cnt:] = 0
                ret += [weights[i]]
            return ret
        else:
            trans = OperatorPropagation.get_edge_transform(edges)
            return OperatorPropagation.reduction_edge(edges, trans, *weights)

    @staticmethod
    def sum_up_multi_edge_ts(edges, *weights, operation_ptrs=None):
        if operation_ptrs is not None:
            em = edges[operation_ptrs]
            wm = [i[operation_ptrs] for i in weights]
            trans = OperatorPropagation.get_edge_transform(em)
            redu = OperatorPropagation.reduction_edge(em, trans, *wm)
            cnt = redu[0].shape[0]
            operation_ptrs = operation_ptrs[:cnt]
            skip_ptrs = operation_ptrs[cnt:]
            edges[operation_ptrs] = redu[0]
            for i in range(len(weights)):
                weights[i][operation_ptrs] = redu[i + 1]
                weights[i][skip_ptrs] = 0
            return skip_ptrs
        else:
            trans = OperatorPropagation.get_edge_transform(edges)
            return OperatorPropagation.reduction_edge(edges, trans, *weights)
    # def generate_hyper_graph(self,
    #                          erase_self_loop=False,
    #                          edges_x=None,
    #                          self_loop_w_only=False,
    #                          edge_duplicate_sgn=None):
    #     # transfer nodes
    #     edge_index2 = (self.community_result[self.graph.edge_index[0]], self.community_result[self.graph.edge_index[1]])
    #     edge_w = trans_prob
    #     max_id = torch.max(self.community_result).long()
    #     trans = None
    #
    #     if erase_self_loop or self_loop_w_only:
    #         idx = edge_index2[0] != edge_index2[1]
    #         if self_loop_w_only:
    #             idw = torch.logical_not(idx)
    #             w0 = cluster_sum(edge_index2[0][idw], edge_w[idw], clip_length=max_id + 1)
    #         edge_w = edge_w[idx]
    #         if edges_x is not None:
    #             edges_x = edges_x[idx]
    #         edge_index2 = edge_index2[0][idx], edge_index2[1][idx]
    #         if edge_duplicate_sgn is not None:
    #             edge_duplicate_sgn = edge_duplicate_sgn[idx]
    #     if len(edge_w) == 0:
    #         return cogdl.data.Graph(edge_index=(torch.LongTensor(), torch.LongTensor()), edge_weight=torch.LongTensor(),
    #                                 x=x)
    #     # calc edge merging mat
    #
    #     if edge_duplicate_sgn is not None:
    #         not_dup = torch.logical_not(edge_duplicate_sgn)
    #         edge_index2_side = (edge_index2[0][not_dup],
    #                             edge_index2[1][not_dup])
    #         edge_index2 = (edge_index2[0][edge_duplicate_sgn],
    #                        edge_index2[1][edge_duplicate_sgn])
    #
    #         edges_w_side = edge_w[not_dup]
    #         edge_w = edge_w[edge_duplicate_sgn]
    #         if edges_x is not None:
    #             edges_x_side = edges_x[not_dup]
    #             edges_x = edges_x[edge_duplicate_sgn]
    #
    #     edge_hash = edge_index2[0] * (max_id + 1) + edge_index2[1]
    #     trans = torch.unique(edge_hash, return_inverse=True)[1]
    #     del edge_hash
    #
    #     # merge weight
    #     cnt_e = trans.max() + 1
    #     edge_weight_2 = cluster_sum(trans, edge_w)
    #
    #     if edges_x is not None:
    #         edges_x = cluster_sum(trans, edges_x)
    #     del edge_w
    #     # merge nodes
    #     # out[trans[i]]=in[i]
    #     out = torch.zeros_like(edge_index2[0][:cnt_e]), torch.zeros_like(edge_index2[1][:cnt_e])
    #     edge_index2 = (out[0].scatter(0, trans, edge_index2[0]), out[1].scatter(0, trans, edge_index2[1]))
    #     del trans
    #
    #     if edge_duplicate_sgn is not None:
    #         edge_index2 = (torch.cat([edge_index2_side[0], edge_index2[0]]),
    #                        torch.cat([edge_index2_side[1], edge_index2[1]]))
    #         edge_weight_2 = torch.cat([edges_w_side, edge_weight_2])
    #         # assert edge_index2[0].shape[0] == edge_weight_2.shape[0]
    #         if edges_x is not None:
    #             edges_x = torch.cat([edges_x_side, edges_x])
    #
    #     if self_loop_w_only:
    #         idx = torch.arange(max_id + 1, device=max_id.device)
    #         edge_index2 = (torch.cat([idx, edge_index2[0]]), torch.cat([idx, edge_index2[1]]))
    #         edge_weight_2 = torch.cat([w0, edge_weight_2])
    #         if edges_x is not None:
    #             sp = [w0.shape[0]]
    #             for i in range(1, len(edges_x.shape)):
    #                 sp.append(edges_x.shape[i])
    #             edges_x = torch.cat([torch.zeros(sp, dtype=edges_x.dtype, device=edges_x.device), edges_x])
    #
    #     if edges_x is not None:
    #         return cogdl.data.Graph(edge_index=edge_index2, edge_weight=edge_weight_2, x=x), edges_x
    #     return cogdl.data.Graph(edge_index=edge_index2, edge_weight=edge_weight_2, x=x)

    # loop0: has self loop
    # ter: threshold of merge count to start merge_all

    centers_proposal = torch.nn.AdaptiveAvgPool2d((15, 15))

    def perform_x(self, img):
        sim = pairwise_cos_sim(img[1].reshape(-1, 3), img.reshape(-1, 3))
        sim_max, sim_max_idx = sim.max(dim=1, keepdim=True)
        mask = torch.zeros_like(sim)  # binary #[B,M,N]
        mask.scatter_(1, sim_max_idx, 1.)
        sim = sim * mask
        sim.unsqueeze(dim=-1).sum(dim=2)
        mask.sum(dim=-1, keepdim=True)



    def perform(self, p=1.0,
                ter=0, contains_self_loops=None,
                adj_cover=None, min_com=1, max_com=math.inf, di_max=False, srt_M=False,
                f_hyper_edge=None, m_scale=None, re_compute = True):
        assert 1 <= min_com <= max_com
        assert 0.0 <= p <= 1.0
        edges, trans_prob = self.enc.graph.edges

        self._log2m = torch.log2(trans_prob.sum())
        if m_scale != None:
            self._log2m += m_scale
        # print(self._log2m)

        operated_cnt = math.inf
        transs = []
        merge_all = False
        if contains_self_loops is None:
            # noinspection PyUnresolvedReferences
            contains_self_loops = bool((edges[:, 0] == edges[:, 1]).any())

        # v1 = None
        vst = None
        dH0 = None

        # vst cached when unchanged
        cache = False
        # only detect altered_e
        # altered_e = None

        current_num_vertices = self.enc.graph.num_vertices

        # t = time.time()

        if re_compute is not True:
            trans = self.enc.node_id
            if adj_cover is None:
                cache = False
                edges = trans[edges]
                edges, trans_prob = OperatorPropagation.sum_up_multi_edge(edges, trans_prob)
                current_num_vertices = edges.max() + 1
                contains_self_loops = True
            else:
                cache = False
                edges = trans[edges]
                edges, trans_prob, adj_cover = OperatorPropagation.sum_up_multi_edge(edges, trans_prob, adj_cover)
                current_num_vertices = edges.max() + 1
                contains_self_loops = True
            transs.append(trans)


        while operated_cnt > ter or not merge_all:

            max_operate_cnt = math.ceil((current_num_vertices - min_com) * p)

            edge_s = edges[:, 0]
            edge_t = edges[:, 1]
            mx = torch.max(edges)
            if operated_cnt <= ter + 1:
                merge_all = True
            # print(trans_prob.shape)
            # print(self.graph.edge_index[1].shape)
            # print("time-x:{}".format(time.time() - t))
            # t = time.time()
            # print(self.enc.graph.num_vertices)
            if not cache:
                v1 = silearn.scatter_sum(trans_prob, edge_t, clip_length= mx + 1).reshape(-1)
                # print(self.enc.graph.stationary_dist)
                vst = v1[edges]

            if contains_self_loops:
                if not cache:
                    g1 = silearn.scatter_sum(trans_prob * (edge_s != edge_t), edge_t, clip_length= mx + 1)
                    gst = g1[edges]
                    vx = vst.sum(dim=1)
                    # gx = gst.sum(dim = 1)

                    # g0s, g0t, g0x = vs, vt, vx
                    # if hyper_g:
                    #     if self.graph.x is None:
                    #         self.graph.x = g1.clone()
                    #     else:
                    #         g0 = self.graph.x
                    #         print(g0.shape)
                    #         g0s = g0[edges[:, 0]]
                    #         g0t = g0[edges[:, 1]]
                    #         g0x = g0s + g0t
                    vin = vst - gst

                    dH1 = (vin[:, 0]) * torch.log2(vst[:, 0]) + (vin[:, 1]) * torch.log2(vst[:, 1]) - (
                                vin[:, 0] + vin[:, 1]) * torch.log2(vx)
                    dH2 = 2 * trans_prob * ((self._log2m) - torch.log2(vx))
                    dH0 = dH1 + dH2
                    op = (dH0 > 0)
                    # 使用M选择合并时
                    # if srt_M:
                    #     dH = - dH2 / dH1 # * (self._log2m)
                    # print(dH1.min())
                    # print(dH2.min())
                    # print(dH.min())
                    # dH = dH0
                    # else:
                    dH = dH0
                    dHM = dH

                else:
                    op = (dH0 > 0)
                    dH = dH0

                if not torch.any(op):
                    break
                if not merge_all:
                    op = (dH >= torch.median(dH[op]))
            else:
                dH = trans_prob * (self._log2m - torch.log2(vst[:, 0] + vst[:, 1]))
                op = (dH >= torch.median(dH[dH > 0]))

            cache = True

            if adj_cover is not None:
                op = torch.logical_and(op, adj_cover > 0)

            # print(f"t1:{ time.time() - t}")

            # print(operated_cnt)
            merge = op
            # rand_idx = torch.randint(0,  2**31,(1, self.enc.graph.num_vertices), device=self.device)[0]
            # noinspection PyTypeChecker
            # merge = torch.logical_and(merge, (vs < vt) + torch.logical_and((vs == vt) , rand_idx[edges[:, 0]] < rand_idx[edges[:, 1]]))
            # merge = torch.logical_and(merge, (vs < vt) + torch.logical_and((vs == vt) , rand_idx[edges[:, 0]] < rand_idx[edges[:, 1]]))
            hash_x = edge_s * 10007 // 1009
            hash_t = edge_t * 10007 // 1009
            merge = torch.logical_and(merge,
                                      torch.logical_or((vst[:, 0] < vst[:, 1]),
                                                       torch.logical_and((vst[:, 0] == vst[:, 1]),
                                                                         hash_x < hash_t)))
            if not torch.any(merge):
                operated_cnt = 0
                continue

            # t = time.time()
            id0 = edge_s
            id1 = edge_t
            if not merge_all:
                dH = dH * (1.0 + 1e-6 * hash_x * 1e-6 * hash_t)

            id0 = id0[merge]
            id1 = id1[merge]
            dH = dH[merge]

            _, dH_amax = silearn.scatter_max(dH, id0)
            # dh_amax[i] = (argmax_j[dH[j]] for id0[j] = i) if \exist i in id0, else dH.shape + 1
            # dH_amax[i] is unique

            dH_amax = dH_amax[dH_amax < dH.shape[0]]  # then dH_amax is a unique set

            operated_cnt = int(dH_amax.shape[0])  # cuda synchronized
            # print(operated_cnt)
            if operated_cnt == 0:
                continue


            # print("max_op:"+str(max_operate_cnt))
            # print(max_operate_cnt)
            # print(operated_cnt)

            # 双向max
            if operated_cnt > max_operate_cnt and di_max:
                id0 = id0[dH_amax]
                id1 = id1[dH_amax]
                dH = dH[dH_amax]
                _, dH_amax = silearn.scatter_max(dH, id1)
                dH_amax = dH_amax[dH_amax < dH.shape[0]]
                operated_cnt = int(dH_amax.shape[0])

            if operated_cnt > max_operate_cnt:
                _, idx = torch.sort(dH[dH_amax], descending=True)
                # idx = torch.randperm(dH_amax.shape[0])
                dH_amax = dH_amax[idx[:max_operate_cnt]]
                operated_cnt = max_operate_cnt
                # p = 1.0

            current_num_vertices -= operated_cnt
            # operated_cnt = ddd_new

            ids = id0[dH_amax]
            idt = id1[dH_amax]

            trans = torch.arange(edges.max() + 1, device=self.enc.graph.device)

            trans[ids] = trans[idt]
            # if operated_cnt < 10:
            #     altered = torch.zeros(self.enc.graph.num_vertices, device=self.enc.graph.device, dtype=torch.bool)
            #     altered[ids] = True
            #     altered[idt] = True
            #     altered_e = torch.nonzero(torch.logical_or(altered[edges[:, 0]],
            #                                  altered[edges[:, 1]]))  # edges
            #
            # else:
            #     altered_e = None
            # trans[id0] = id1
            # trans[i] = j: label node i to j
            # print(operated_cnt)
            lg_merge = math.log2(operated_cnt + 2)

            # todo: test speed: limit var
            # var = #trans != torch.arange(self.enc.graph.num_vertices, device=self.enc.graph.device)
            for i in range(int(lg_merge)):
                # ids[var] = trans[trans[var]]
                # old = trans[ids]
                trans[ids] = trans[trans[ids]]
                # ids = torch.nonzero(trans[ids] != old)

            # print(time.time() - t)

            # torch.tensor([id0])
            # torch.tensor([id1])

            # t = time.time()
            # failed = torch.logical_or(trans == torch.arange(self.enc.graph.num_vertices) , altered) == 0
            # print(ids)
            # print(idt)
            # print(torch.nonzero(failed))

            # print(torch.nonzero(altered))
            # print(torch.nonzero(trans != torch.arange(self.enc.graph.num_vertices)))

            # compress id allocation

            trans = torch.unique(trans, return_inverse=True)[1]
            # _, trans, counts= torch.unique(trans, return_inverse=True, return_counts = True)


            # self.community_result = trans
            transs.append(trans)
            # print(trans)

            if self.enc.graph.num_vertices - operated_cnt == min_com:
                break
            # print(f"t2:{ time.time() - t}")

            if adj_cover is None:
                cache = False

                edges = trans[edges]
                edges, trans_prob = OperatorPropagation.sum_up_multi_edge(edges, trans_prob)

                # operated = torch.nonzero(torch.sum(counts[edges] > 1, dim = -1)).reshape(-1)
                # print(operated)
                # OperatorPropagation.sum_up_multi_edge(edges, trans_prob, operation_ptrs=torch.nonzero(merge).reshape(-1))


            else:
                cache = False
                edges = trans[edges]
                edges, trans_prob, adj_cover = OperatorPropagation.sum_up_multi_edge(edges, trans_prob, adj_cover)
                # trans_prob = trans_prob + f_hyper_edge(self.graph.x,
                #                                                                edges[:, 0],
                #                                                                edges[:, 1],
                #                                                                trans_prob,
                #                                                                adj_cover)

            contains_self_loops = True
            # break

            # print(time.time() - t, operated_cnt)
        if len(transs) != 0:
            trans = transs[-1]
            for i in reversed(range(len(transs) - 1)):
                trans = trans[transs[i]]

            self.enc.node_id = trans
        else:

            com0 = torch.arange(self.enc.graph.num_vertices, device=self.enc.graph.device)
            self.enc.node_id = com0

    def iterative_merge(self, verbose = False, min_com = 1,
                        max_iteration = 30, tau = 0.1, sample_ratio = 0.5, p = 0.5, m_scale = -1):
        prob_e = torch.ones(self.enc.graph.num_edges, device=self.enc.graph.device)
        edges, _ = self.enc.graph.edges
        for i in range(max_iteration):

            rand = torch.rand(self.enc.graph.num_edges, device=self.enc.graph.device) * prob_e
            bound = torch.msort(rand)[int((prob_e.shape[0] - 1) * sample_ratio)]

            cover_adj = rand >= bound
            self.perform(adj_cover = cover_adj,min_com = min_com, p = p, m_scale= m_scale)
            self.perform(min_com = min_com, re_compute=False, p = p, m_scale= m_scale)
            c = torch.logical_not(cover_adj)
            operated = self.enc.node_id[edges[:, 0]] == self.enc.node_id[edges[:, 1]]
            # prob_e[torch.logical_and(cover_adj,torch.logical_not(operated))] *= 1 - tau
            prob_e[torch.logical_and(c,operated)] /= 1 - tau
            print(prob_e)

            print(self.enc.structural_entropy(reduction="sum"))

    # By Hujin

    # def iterative_merge_c(self, verbose = False, min_com = 1,
    #                     max_iteration = 30, tau = 0.1, sample_ratio = 0.5, p = 0.5, m_scale = 0):
    #     prob_e = torch.ones(self.enc.graph.num_edges, device=self.enc.graph.device)
    #     edges, _ = self.enc.graph.edges
    #     for i in range(max_iteration):
    #
    #         rand = torch.rand(self.enc.graph.num_edges, device=self.enc.graph.device) * prob_e
    #         bound = torch.msort(rand)[int((prob_e.shape[0] - 1) * sample_ratio)]
    #
    #         cover_adj = rand >= bound
    #         self.process_c(adj_cover = cover_adj)
    #         self.process_fast(min_com = min_com, re_compute=False, p = p, m_scale=m_scale)
    #         c = torch.logical_not(cover_adj)
    #         operated = self.enc.node_id[edges[:, 0]] == self.enc.node_id[edges[:, 1]]
    #         prob_e[torch.logical_and(c,torch.logical_not(operated))] *= 1 - tau
    #         prob_e[torch.logical_and(c,operated)] /= 1 - tau
    #         print(prob_e)
    #
    #         print(self.enc.structural_entropy(reduction="sum"))

    # def exchange_nodes(self, vin, vst, vx, trans_prob):
    #     dH1 = (vin[:, 0]) * torch.log2(vst[:, 0])
    #     dH2 = 2 * trans_prob * ((self._log2m) - torch.log2(vx))
    #
    #     dH3 = (vin[:, 0]) * torch.log2(vst[:, 0])
    #             vin[:, 0] + vin[:, 1]) * torch.log2(vx)
    #     dH4 = 2 * trans_prob * ((self._log2m) - torch.log2(vx))
    #















