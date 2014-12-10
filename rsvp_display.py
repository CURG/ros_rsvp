from __future__ import print_function

__author__ = 'rbtying'

import pygame
from rsvp_msgs.msg import RankAction, RankResult
from image_converter import ImageConverter
from bci_engine import BCIEngine
from trial import Trial

# ROS
import actionlib


class RSVPDisplay(object):
    PRESENTATION_FREQUENCY = 4
    PRESENTATION_DELAY = int(1000.0 / PRESENTATION_FREQUENCY + 0.5)
    FRAMERATE = 60

    # random event id
    EVENT_ID = pygame.USEREVENT + 1

    def __init__(self, hostname='localhost', port=4444, size=(640, 480), use_bci=True):
        if use_bci:
            self.bci = BCIEngine(hostname=hostname, port=port)
        else:
            self.bci = None
        self.size = size
        self.window = pygame.display.set_mode(self.size)
        pygame.display.set_caption('RSVP BCI')
        self.screen = pygame.display.get_surface()
        self.font = pygame.font.Font(None, 36)

        self.clock = pygame.time.Clock()

        self.running = True
        self.ranking = False

        self.action_server = actionlib.SimpleActionServer('rank', RankAction, self.rank_image_cb, False)
        self.action_server.start()

        self.trial = None

        self.reset()

    def rank_image_cb(self, msg):
        print(
            'Received message with {} compressed_imgs, {} imgs, {} strs'.format(len(msg.compressed_imgs), len(msg.imgs),
                                                                                len(msg.strs)))
        if self.trial and not self.trial.mode in (Trial.State.ABORTED, Trial.State.COMPLETED):
            print('Aborting due to ongoing trial')
            self.action_server.set_aborted()
            return

        self.reset()

        if len(msg.compressed_imgs) > 0:
            self.screen.fill((255, 255, 255))
            self.screen.blit(self.font.render(
                'Received {} images'.format(len(msg.compressed_imgs)), 1, (0, 0, 0)), (40, self.size[1] / 2))
            pygame.display.flip()

            scaled_imgs = [ImageConverter.from_ros(img) for img in msg.compressed_imgs]
            scaled_imgs = [pygame.transform.scale(img, self.size) for img in scaled_imgs]

            self.trial = Trial(zip(msg.option_ids, scaled_imgs), size=self.size, preview_time=5000,
                               image_time=self.PRESENTATION_DELAY)

            self.ranking = True

            self.bci and self.bci.begin_block()

            pygame.time.set_timer(self.EVENT_ID, self.trial.show_next_image(self.screen, self.bci))
            pygame.display.flip()

            while self.ranking:
                pygame.time.wait(100)
        else:
            self.action_server.set_aborted()

    def reset(self):
        self.ranking = False
        self.screen.fill((0, 0, 0))
        self.trial = None

        if self.bci and self.bci.in_block:
            self.bci.end_block()
        pygame.time.set_timer(self.EVENT_ID, 0)

        reset_str = 'BCI Reset' if self.bci else 'SIMULATION MODE'
        self.screen.blit(self.font.render(reset_str, 1, (255, 255, 255)), (10, 10))
        pygame.display.flip()

    def do_loop(self):
        while self.running:
            self.clock.tick(self.FRAMERATE)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.reset()
                    return
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.reset()
                        return
                elif event.type == self.EVENT_ID:
                    if self.trial:
                        pygame.time.set_timer(self.EVENT_ID, self.trial.show_next_image(self.screen, self.bci))
                        pygame.display.flip()

                        if self.trial.mode == Trial.State.COMPLETED:
                            self.bci and self.bci.end_block()

                            try:
                                print('Trial completed')
                                results = self.trial.process_results(self.screen, self.bci)
                                print('Results of trial: {}'.format(results))
                                self.action_server.set_succeeded(results)
                                pygame.display.flip()
                                self.trial = None
                                self.ranking = False
                            except RuntimeError:
                                print('Trial insufficient, rescheduling')
                                self.bci and self.bci.begin_block()
                                pygame.time.set_timer(self.EVENT_ID, self.trial.reset())
                                pygame.display.flip()
                        elif self.trial.mode == Trial.State.ABORTED:
                            print('Trial aborted')
                            self.action_server.set_aborted()
                            self.ranking = False
                            self.trial = None
                            self.bci and self.bci.end_block()
                            self.reset()
