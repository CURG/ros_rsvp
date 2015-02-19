from __future__ import print_function

__author__ = 'rbtying'
import random
import pygame
import heapq
import math
import numpy as np
from bci_engine import BlockResult
from rsvp_msgs.msg import RankResult


class OptionResult(object):
    """
    Helper class to store option result data
    """
    def __init__(self, idx, expected_counts):
        self.eegs = []
        self.sort_positions = []
        self.idx = idx
        self.expected_counts = expected_counts

    @property
    def average_eeg(self):
        return np.average(self.eegs)

    @property
    def stdev_eeg(self):
        return np.std(self.eegs)

    @property
    def average_sort_position(self):
        return np.average(self.sort_positions)

    @property
    def stdev_sort_position(self):
        return np.std(self.sort_positions)

    @property
    def avg_best_two(self):
        return np.mean(sorted(self.eegs)[:2])

    def __str__(self):
        return 'id: {} eegs: [{}] positions: [{}]'.format(self.idx, ','.join(map(str, self.eegs)), ','.join(map(str, self.sort_positions)))


class Trial(object):
    """
    Represents a single set of stimuli/options that we select from
    """

    class State(object):
        INIT = 0
        PREVIEW = 1
        RUNNING = 2
        COMPLETED = 3
        ABORTED = 4

    BG_COLORS = [
        (255, 0, 0), (255, 102, 0), (255, 166, 64), (230, 226, 172), (0, 230, 0), (61, 242, 157), (0, 82, 102),
        (182, 190, 242), (135, 115, 153), (242, 0, 129), (191, 96, 134), (204, 0, 0), (229, 161, 115), (153, 122, 0),
        (109, 115, 86), (0, 217, 0), (38, 153, 99), (61, 182, 242), (37, 0, 140), (43, 0, 64), (255, 191, 225),
        (89, 0, 12), (217, 170, 163), (64, 45, 32), (76, 65, 19), (85, 128, 0), (0, 179, 0), (121, 242, 218),
        (32, 57, 128), (137, 108, 217), (230, 115, 222), (77, 57, 68), (229, 57, 80), (115, 52, 29), (127, 68, 0),
        (229, 218, 57), (43, 51, 38), (16, 64, 29), (35, 140, 133), (38, 48, 77), (157, 61, 242), (115, 0, 92),
        (51, 0, 20)
    ]
    BG_COLORS = [(50,50,50) for i in range(36)]

    def __init__(self, options, size=(640, 480), preview_time=1000.0, image_time=100, min_repeat=3, max_repeat=7):
        """
        Creates a trial
        :param options: [(id, Surface)...] list of pygame Surfaces to display
        :param size: the size of the window
        :param preview_time: the amount of time to show the preview
        :param image_time: the amount of time to show each image
        :param min_repeat: the minimum number of times each image is repeated
        :param max_repeat: the maximum number of times each image is repeated
        :return:
        """
        self.mode = Trial.State.INIT
        self.size = size
        self.preview_time = preview_time
        self.image_time = image_time
        self.options = [(opt[0], pygame.transform.smoothscale(opt[1], self.size)) for opt in options]
        self.font = pygame.font.Font(None, 36)

        self.min_repeat = max(1, min_repeat)
        self.max_repeat = max(self.min_repeat, max_repeat)

        self.index_list, self.option_counts = self._construct_trial()

        self.index_ptr = 0
        self.selected_index_ptr = None

        random.shuffle(self.BG_COLORS)
        self.results = None

    def reset(self):
        self.mode = Trial.State.INIT
        self.index_ptr = 0
        self.selected_index_ptr = None
        self.results = None
        return self.preview_time

    def show_next_image(self, screen, bci=None):
        """
        Shows the next image in the sequence, i.e. init -> preview -> sequence -> done
        :param screen:
        :param bci:
        :return: the time the image should stay on screen before show_next_image is called again
        """
        if self.mode == Trial.State.INIT:
            self.mode = Trial.State.PREVIEW
            screen.fill((0, 0, 0))
            self._display_preview_image(screen)
            screen.blit(self.font.render(
                'Previewing {} images'.format(len(self.options)), 1, (255, 255, 255)), (40, self.size[1] / 2))
            return self.preview_time
        elif self.mode in (Trial.State.PREVIEW, Trial.State.RUNNING):
            if self.mode == Trial.State.PREVIEW:
                self.mode = Trial.State.RUNNING
                self.index_ptr = 0
            else:
                self.index_ptr += 1

            if self.index_ptr >= len(self.index_list):
                self.mode = Trial.State.COMPLETED
                return 0
            else:
                bci and bci.mark_unlabeled()
                im_idx = self.index_list[self.index_ptr]
                screen.fill(self.BG_COLORS[im_idx % len(self.BG_COLORS)])
                screen.blit(self.options[im_idx][1], (0, 0))
                screen.blit(self.font.render(str(self.options[im_idx][0]), 1, (255, 255, 255)), (20, 20))
                return self.image_time
        else:
            return 0

    def process_results(self, screen, bci):
        """
        Processes the results of the last block, and shows the selected image on screen
        :param screen:
        :param bci:
        :return:
        """
        if bci:
            self.results = bci.get_block_results()
        else:
            self.results = BlockResult.random_blocks(1, self.option_counts, self.index_list)

        eegs = []
        option_results = [OptionResult(opt[0], self.option_counts[idx]) for idx, opt in enumerate(self.options)]
        self.option_results = option_results

        for result in self.results:
            option_idx = self.index_list[result.image_id - 1]
            option_results[option_idx].eegs.append(result.eeg)
            option_results[option_idx].sort_positions.append(result.sort_position)
            eegs.append(result.eeg)

        option_results = sorted(option_results, key=lambda x: -x.avg_best_two)

        overall_eeg_med = np.median(eegs)
        overall_eeg_std = np.std(eegs)

        def z(v):
            return (overall_eeg_med - v) / overall_eeg_std

        def percentage_correct(r):
            num_correct = sum(1 if abs(z(eeg)) > 0.5 else 0 for eeg in r.eegs)
            return num_correct * 1.0 / r.expected_counts

        result = RankResult()
        result.option_ids = [res.idx for res in option_results]
        result.confidences = [z(res.average_eeg) * percentage_correct(res) for res in option_results]

        best_option = result.confidences[0]
        avg_of_other_options = np.mean(result.confidences[1:])
        std_of_other_options = np.std(result.confidences[1:])

        # print([res.average_eeg for res in option_results])
        # print(result.confidences)
        # print(('Best option', best_option))
        # print(('avg, std', avg_of_other_options, std_of_other_options))

        print(result, best_option, avg_of_other_options, std_of_other_options,
              abs(best_option - avg_of_other_options) / std_of_other_options,
              abs(std_of_other_options / overall_eeg_std))

        if (abs(best_option - avg_of_other_options) / std_of_other_options) < 2: #  or abs(std_of_other_options / overall_eeg_std) > 0.9:
            raise RuntimeError('not a good result')

        # display best option
        im_idx = -1
        for (idx, opt) in enumerate(self.options):
            if opt[0] == result.option_ids[0]:
                im_idx = idx
                break

        if im_idx >= 0:
            screen.fill(self.BG_COLORS[im_idx % len(self.BG_COLORS)])
            screen.blit(self.options[im_idx][1], (0, 0))
            screen.blit(self.font.render(
                'Selected option id: {}, conf: {}'.format(result.option_ids[0], result.confidences[0]), 1,
                (255, 255, 255)), (40, self.size[1] / 8))

        return result

    def _display_preview_image(self, screen):
        """
        Creates a preview image which shows each of the individual images
        in a grid
        :return:
        """
        elements_per_side = int(math.ceil(math.sqrt(len(self.options))))

        grid_w = self.size[0] / elements_per_side
        grid_h = self.size[1] / elements_per_side

        counter = 0
        for idx in range(len(self.options)):
            row = counter / elements_per_side
            col = counter % elements_per_side
            rect = pygame.Rect((row * grid_w, col * grid_h), (grid_w, grid_h))
            subsurf = screen.subsurface(rect)
            subsurf.fill(self.BG_COLORS[idx % len(self.BG_COLORS)])
            subsurf.blit(pygame.transform.smoothscale(self.options[idx][1], (grid_w, grid_h)), (0, 0))
            subsurf.blit(self.font.render(str(self.options[idx][0]), 1, (255, 255, 255)), (20, 20))
            counter += 1

    def _construct_trial(self):
        """
        Creates a sequence of indexes which minimizes the chance that adjacent
        indices are equal
        :return: a list of indexes, and their counts
        """
        option_counts = [random.randrange(self.min_repeat, self.max_repeat) for _ in self.options]
        index_list = list(self._nonadjacent(option_counts))
        random.shuffle(index_list)

        return index_list, option_counts

    @staticmethod
    def _nonadjacent(option_counts):
        """
        Constructs maximally-unsorted list of indices given a list of frequencies
        :param option_counts: A list of frequencies per index
        :return: generator for indices in maximal unsorted order
        """
        heap = [(-count, key) for (key, count) in enumerate(option_counts)]
        heapq.heapify(heap)
        count, key = 0, None
        while heap:
            count, key = heapq.heapreplace(heap, (count, key)) if count else heapq.heappop(heap)
            yield key
            count += 1
        for index in xrange(-count):
            yield key
