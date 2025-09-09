"""
GPU guard system for resource management and budget control.

This module implements the GPU guard that controls when GPU-intensive operations
like tuning and retraining can be submitted, based on concurrency limits and
daily budgets.
"""

import time
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from .schema import GpuGuard
from .metrics import get_metrics

logger = logging.getLogger(__name__)

@dataclass
class GpuJob:
    """Represents a GPU job."""
    job_id: str
    job_type: str
    submitted_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    status: str = "pending"  # pending, running, completed, failed
    estimated_duration_s: float = 300.0  # 5 minutes default

class GpuGuardSystem:
    """GPU guard system for managing GPU resource allocation."""
    
    def __init__(self, config: GpuGuard):
        self.config = config
        self.metrics = get_metrics()
        
        # Job tracking
        self.jobs: Dict[str, GpuJob] = {}
        self.active_jobs: List[str] = []
        self.job_queue: List[str] = []
        
        # Budget tracking
        self.daily_budget_seconds = config.daily_budget_hours * 3600
        self.budget_used_today = 0.0
        self.last_budget_reset = time.time()
        
        # Cooldown tracking
        self.last_job_completion = 0.0
        
        # Statistics
        self.total_jobs_submitted = 0
        self.total_jobs_completed = 0
        self.total_budget_used = 0.0
        
        logger.info(f"✅ GPU Guard initialized: max_concurrent={config.max_concurrent}, "
                   f"daily_budget={config.daily_budget_hours}h, cooldown={config.cooldown_minutes}m")
    
    def can_submit_job(self, job_type: str = "tuning") -> tuple[bool, str]:
        """
        Check if a new GPU job can be submitted.
        
        Returns:
            (can_submit, reason)
        """
        current_time = time.time()
        
        # Check if we're in cooldown period
        if current_time - self.last_job_completion < self.config.cooldown_minutes * 60:
            remaining_cooldown = self.config.cooldown_minutes * 60 - (current_time - self.last_job_completion)
            return False, f"Cooldown active for {remaining_cooldown:.0f}s"
        
        # Check concurrency limit
        if len(self.active_jobs) >= self.config.max_concurrent:
            return False, f"Concurrency limit reached ({self.config.max_concurrent})"
        
        # Check daily budget
        self._update_daily_budget()
        if self.budget_used_today >= self.daily_budget_seconds:
            return False, f"Daily budget exhausted ({self.budget_used_today:.0f}s/{self.daily_budget_seconds:.0f}s)"
        
        # Check if there's enough budget for a typical job
        estimated_job_duration = 300.0  # 5 minutes default
        if self.budget_used_today + estimated_job_duration > self.daily_budget_seconds:
            return False, f"Insufficient budget for job (need {estimated_job_duration:.0f}s, have {self.daily_budget_seconds - self.budget_used_today:.0f}s)"
        
        return True, "OK"
    
    def submit_job(self, job_id: str, job_type: str, estimated_duration_s: float = 300.0) -> bool:
        """
        Submit a new GPU job.
        
        Args:
            job_id: Unique job identifier
            job_type: Type of job (tuning, retrain, etc.)
            estimated_duration_s: Estimated job duration in seconds
            
        Returns:
            True if job was submitted, False otherwise
        """
        can_submit, reason = self.can_submit_job(job_type)
        
        if not can_submit:
            logger.warning(f"❌ Cannot submit GPU job {job_id}: {reason}")
            return False
        
        # Create job record
        job = GpuJob(
            job_id=job_id,
            job_type=job_type,
            submitted_at=time.time(),
            estimated_duration_s=estimated_duration_s
        )
        
        self.jobs[job_id] = job
        self.job_queue.append(job_id)
        self.total_jobs_submitted += 1
        
        # Record metrics
        self.metrics.record_gpu_job_submitted(job_type)
        
        logger.info(f"✅ Submitted GPU job {job_id} ({job_type}, est. {estimated_duration_s:.0f}s)")
        return True
    
    def start_job(self, job_id: str) -> bool:
        """Mark a job as started."""
        if job_id not in self.jobs:
            logger.error(f"❌ Job {job_id} not found")
            return False
        
        job = self.jobs[job_id]
        if job.status != "pending":
            logger.error(f"❌ Job {job_id} is not pending (status: {job.status})")
            return False
        
        job.status = "running"
        job.started_at = time.time()
        
        if job_id in self.job_queue:
            self.job_queue.remove(job_id)
        
        self.active_jobs.append(job_id)
        
        logger.info(f"🚀 Started GPU job {job_id}")
        return True
    
    def complete_job(self, job_id: str, success: bool = True) -> bool:
        """Mark a job as completed."""
        if job_id not in self.jobs:
            logger.error(f"❌ Job {job_id} not found")
            return False
        
        job = self.jobs[job_id]
        if job.status != "running":
            logger.error(f"❌ Job {job_id} is not running (status: {job.status})")
            return False
        
        job.status = "completed" if success else "failed"
        job.completed_at = time.time()
        
        # Calculate actual duration and update budget
        if job.started_at:
            actual_duration = job.completed_at - job.started_at
            self.budget_used_today += actual_duration
            self.total_budget_used += actual_duration
            
            # Record metrics
            self.metrics.record_gpu_job_completed(job.job_type, job.status, actual_duration)
        
        # Remove from active jobs
        if job_id in self.active_jobs:
            self.active_jobs.remove(job_id)
        
        self.total_jobs_completed += 1
        self.last_job_completion = time.time()
        
        logger.info(f"✅ Completed GPU job {job_id} ({job.status}, duration: {actual_duration:.0f}s)")
        return True
    
    def fail_job(self, job_id: str, reason: str = "Unknown error") -> bool:
        """Mark a job as failed."""
        if job_id not in self.jobs:
            logger.error(f"❌ Job {job_id} not found")
            return False
        
        job = self.jobs[job_id]
        job.status = "failed"
        job.completed_at = time.time()
        
        # Remove from active jobs and queue
        if job_id in self.active_jobs:
            self.active_jobs.remove(job_id)
        if job_id in self.job_queue:
            self.job_queue.remove(job_id)
        
        logger.warning(f"❌ Failed GPU job {job_id}: {reason}")
        return True
    
    def _update_daily_budget(self):
        """Update daily budget tracking."""
        current_time = time.time()
        
        # Reset budget if it's a new day
        if current_time - self.last_budget_reset >= 86400:  # 24 hours
            self.budget_used_today = 0.0
            self.last_budget_reset = current_time
            logger.info("🔄 Reset daily GPU budget")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current GPU guard status."""
        self._update_daily_budget()
        
        return {
            "guard_ok": self.can_submit_job()[0],
            "active_jobs": len(self.active_jobs),
            "queued_jobs": len(self.job_queue),
            "budget_used_today_s": self.budget_used_today,
            "budget_remaining_s": self.daily_budget_seconds - self.budget_used_today,
            "budget_utilization": self.budget_used_today / self.daily_budget_seconds,
            "total_jobs_submitted": self.total_jobs_submitted,
            "total_jobs_completed": self.total_jobs_completed,
            "cooldown_remaining_s": max(0, self.config.cooldown_minutes * 60 - (time.time() - self.last_job_completion)),
            "config": {
                "max_concurrent": self.config.max_concurrent,
                "daily_budget_hours": self.config.daily_budget_hours,
                "cooldown_minutes": self.config.cooldown_minutes
            }
        }
    
    def update_metrics(self):
        """Update Prometheus metrics."""
        status = self.get_status()
        
        self.metrics.update_gpu_guard_signals(
            queue_depth=status["queued_jobs"],
            concurrent_jobs=status["active_jobs"],
            budget_remaining_s=status["budget_remaining_s"],
            guard_ok=status["guard_ok"]
        )
    
    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Clean up old job records."""
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        jobs_to_remove = []
        for job_id, job in self.jobs.items():
            if current_time - job.submitted_at > max_age_seconds:
                jobs_to_remove.append(job_id)
        
        for job_id in jobs_to_remove:
            del self.jobs[job_id]
        
        if jobs_to_remove:
            logger.info(f"🧹 Cleaned up {len(jobs_to_remove)} old job records")
    
    async def start_background_tasks(self):
        """Start background maintenance tasks."""
        async def update_metrics_task():
            while True:
                try:
                    self.update_metrics()
                    await asyncio.sleep(30)  # Update every 30 seconds
                except Exception as e:
                    logger.error(f"Error in metrics update task: {e}")
                    await asyncio.sleep(60)
        
        async def cleanup_task():
            while True:
                try:
                    self.cleanup_old_jobs()
                    await asyncio.sleep(3600)  # Cleanup every hour
                except Exception as e:
                    logger.error(f"Error in cleanup task: {e}")
                    await asyncio.sleep(3600)
        
        # Start background tasks
        asyncio.create_task(update_metrics_task())
        asyncio.create_task(cleanup_task())
        
        logger.info("🚀 Started GPU guard background tasks")
