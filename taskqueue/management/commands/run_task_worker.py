"""
Management command to run the background task worker with optimized settings.
"""

import logging
import time
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from background_task.tasks import tasks, Task
from background_task.models import Task as BGTask

from taskqueue.tasks import log_queue_metrics, get_queue_metrics

logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger('taskqueue.metrics')


class Command(BaseCommand):
    """
    Custom management command to run the background task worker with optimized settings
    and additional monitoring capabilities.
    """
    
    help = 'Runs the background task worker with optimized settings and monitoring'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--threads',
            type=int,
            default=getattr(settings, 'BACKGROUND_TASK_ASYNC_THREADS', 4),
            help='Number of async threads',
        )
        parser.add_argument(
            '--queue',
            type=str,
            default=None,
            help='Queue name to process (leave empty for all queues)',
        )
        parser.add_argument(
            '--log-metrics',
            action='store_true',
            default=getattr(settings, 'BACKGROUND_TASK_METRICS_ENABLED', True),
            help='Enable periodic metrics logging',
        )
        parser.add_argument(
            '--metrics-interval',
            type=int,
            default=getattr(settings, 'BACKGROUND_TASK_METRICS_INTERVAL', 15),
            help='Minutes between metrics logging',
        )
    
    def handle(self, *args, **options):
        """
        Run the worker process with the specified options.
        """
        threads = options['threads']
        queue_name = options['queue']
        log_metrics_enabled = options['log_metrics']
        metrics_interval = options['metrics_interval']
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting background task worker with {threads} threads"
                f"{f' for queue {queue_name}' if queue_name else ''}"
            )
        )
        
        # Log initial metrics
        if log_metrics_enabled:
            self.log_metrics()
            # Schedule periodic metrics logging
            log_queue_metrics(repeat=metrics_interval * 60)  # Convert to seconds
        
        # Configure worker settings
        tasks.MAX_ATTEMPTS = getattr(settings, 'MAX_ATTEMPTS', 3)
        tasks.MAX_RUN_TIME = getattr(settings, 'MAX_RUN_TIME', 3600)
        tasks.BACKGROUND_TASK_RUN_ASYNC = getattr(settings, 'BACKGROUND_TASK_RUN_ASYNC', False)
        
        # Additional optimized settings
        queue_limit = getattr(settings, 'BACKGROUND_TASK_QUEUE_LIMIT', 50)
        sleep_seconds = getattr(settings, 'BACKGROUND_TASK_SLEEP_SECONDS', 5.0)
        priority_ordering = getattr(settings, 'BACKGROUND_TASK_PRIORITY_ORDERING', '-priority')
        
        # Start the worker process
        try:
            self.stdout.write("Worker process started. Press Ctrl+C to stop.")
            
            # Run the worker with our custom settings
            tasks.run_tasks(
                queue_name=queue_name,
                log=logger,
                limit=queue_limit,
                duration=0,  # Run indefinitely
                sleep=sleep_seconds,
                ordering=priority_ordering,
                worker_name=f"worker-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            )
            
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Worker process stopped by user"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Worker process error: {str(e)}"))
            logger.error("Worker process error", exc_info=True)
    
    def log_metrics(self):
        """
        Log current task queue metrics.
        """
        metrics = get_queue_metrics()
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Queue metrics: "
                f"pending={metrics['pending_count']}, "
                f"processing={metrics['processing_count']}, "
                f"completed_24h={metrics['completed_count']}, "
                f"failed_24h={metrics['failed_count']}, "
                f"scheduled={metrics['scheduled_count']}, "
                f"avg_time={metrics['avg_processing_time']:.2f}s"
            )
        )
        
        # Also log to the metrics logger
        metrics_logger.info(
            f"Queue metrics: "
            f"pending={metrics['pending_count']}, "
            f"processing={metrics['processing_count']}, "
            f"completed_24h={metrics['completed_count']}, "
            f"failed_24h={metrics['failed_count']}, "
            f"scheduled={metrics['scheduled_count']}, "
            f"avg_time={metrics['avg_processing_time']:.2f}s"
        )