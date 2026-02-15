"""Compliance State Tracker for Checklist Mode.

Manages the state of checklist-mode rules to prevent spam.
When a checklist rule is satisfied, it remains compliant for the validity duration.

State is persisted to a JSON file so it survives server restarts.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import hashlib

from backend.models.schemas import PolicyRule, ChecklistState, ChecklistItem

logger = logging.getLogger(__name__)

# Persistence file path — stored alongside the backend module
_STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "compliance_state.json"
)


class ComplianceStateTracker:
    """Tracks compliance state for checklist-mode rules.
    
    This prevents spam by remembering when rules were satisfied.
    For example, if someone shows their badge, we remember it for 8 hours.
    
    State is automatically persisted to disk on every update and loaded on startup.
    Thread-safe via a reentrant lock.
    """
    
    def __init__(self, state_file: str = _STATE_FILE):
        # state storage: {person_id: {rule_hash: ChecklistState}}
        self.states: Dict[str, Dict[str, ChecklistState]] = {}
        self._state_file = state_file
        self._lock = threading.RLock()
        self._load_from_disk()
        
    def _hash_rule(self, rule: PolicyRule) -> str:
        """Generate a unique hash for a rule based on its description."""
        return hashlib.md5(rule.description.encode()).hexdigest()[:8]
    
    def _load_from_disk(self):
        """Load persisted state from JSON file on startup."""
        if not os.path.exists(self._state_file):
            logger.info("No saved compliance state found — starting fresh.")
            return
        try:
            with open(self._state_file, "r") as f:
                raw = json.load(f)
            self.import_states(raw)
            total_rules = sum(len(v) for v in self.states.values())
            logger.info(
                f"📂 Loaded compliance state: {len(self.states)} people, "
                f"{total_rules} rule states from {self._state_file}"
            )
            # Clean up expired entries on load
            self.clear_expired()
        except Exception as e:
            logger.warning(f"Failed to load compliance state: {e}")
    
    def _save_to_disk(self):
        """Persist current state to JSON file (called on every mutation)."""
        try:
            data = self.get_all_states()
            with open(self._state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save compliance state: {e}")
    
    def check_compliance(
        self, 
        person_id: str, 
        rule: PolicyRule,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, Optional[ChecklistState]]:
        """Check if a person is currently compliant with a checklist rule.
        
        Returns:
            (is_compliant, state) - True if still valid, False if expired/pending
        """
        # Incident mode rules are never cached
        if rule.mode != "checklist":
            return False, None
            
        current_time = current_time or datetime.now(timezone.utc)
        rule_hash = self._hash_rule(rule)
        
        with self._lock:
            # Check if we have state for this person and rule
            if person_id not in self.states:
                return False, None
                
            if rule_hash not in self.states[person_id]:
                return False, None
                
            state = self.states[person_id][rule_hash]
            
            # Check if compliance has expired
            if state.expires_at and current_time > state.expires_at:
                state.status = "expired"
                logger.info(f"Checklist compliance expired for {person_id} on rule: {rule.description[:50]}")
                self._save_to_disk()
                return False, state
                
            # Still compliant
            if state.status == "compliant":
                logger.debug(f"Checklist still valid for {person_id} on rule: {rule.description[:50]}")
                return True, state
                
        return False, state
    
    def update_compliance(
        self,
        person_id: str,
        rule: PolicyRule,
        compliant: bool,
        current_time: Optional[datetime] = None
    ) -> ChecklistState:
        """Update compliance state for a checklist rule.
        
        When someone becomes compliant, we remember it for the validity duration.
        """
        # Only track checklist mode
        if rule.mode != "checklist":
            return None
            
        current_time = current_time or datetime.now(timezone.utc)
        rule_hash = self._hash_rule(rule)
        
        with self._lock:
            # Initialize person's states if needed
            if person_id not in self.states:
                self.states[person_id] = {}
                
            # Create or update state
            if compliant:
                # Calculate expiration
                expires_at = None
                if rule.validity_duration:
                    expires_at = current_time + timedelta(seconds=rule.validity_duration)
                    
                state = ChecklistState(
                    rule_id=rule_hash,
                    person_id=person_id,
                    status="compliant",
                    last_verified=current_time,
                    expires_at=expires_at
                )
                
                self.states[person_id][rule_hash] = state
                
                logger.info(
                    f"✅ Checklist compliance updated for {person_id} on rule: {rule.description[:50]}"
                    f" (valid until {expires_at.isoformat() if expires_at else 'forever'})"
                )
            else:
                # Mark as pending (needs to be shown again)
                state = ChecklistState(
                    rule_id=rule_hash,
                    person_id=person_id,
                    status="pending",
                    last_verified=None,
                    expires_at=None
                )
                self.states[person_id][rule_hash] = state
            
            # Persist after every mutation
            self._save_to_disk()
                
        return state
    
    def get_checklist(
        self, 
        person_id: str,
        rules: List[PolicyRule],
        current_time: Optional[datetime] = None
    ) -> List[ChecklistItem]:
        """Get the current checklist status for a person.
        
        Returns a list of checklist items with their current status.
        """
        current_time = current_time or datetime.now(timezone.utc)
        checklist = []
        
        with self._lock:
            for rule in rules:
                # Only include checklist-mode rules
                if rule.mode != "checklist":
                    continue
                    
                # Check current state
                is_compliant, state = self.check_compliance(person_id, rule, current_time)
                
                # Calculate time remaining
                time_remaining = None
                if state and state.expires_at and state.status == "compliant":
                    delta = state.expires_at - current_time
                    time_remaining = max(0, int(delta.total_seconds()))
                    
                item = ChecklistItem(
                    rule=rule,
                    status=state.status if state else "pending",
                    last_verified=state.last_verified if state else None,
                    expires_at=state.expires_at if state else None,
                    time_remaining=time_remaining
                )
                checklist.append(item)
            
        return checklist
    
    def clear_expired(self, current_time: Optional[datetime] = None):
        """Clean up expired states to save memory."""
        current_time = current_time or datetime.now(timezone.utc)
        
        with self._lock:
            removed = 0
            for person_id in list(self.states.keys()):
                for rule_hash in list(self.states[person_id].keys()):
                    state = self.states[person_id][rule_hash]
                    if state.expires_at and current_time > state.expires_at:
                        del self.states[person_id][rule_hash]
                        removed += 1
                # Remove empty person entries
                if not self.states[person_id]:
                    del self.states[person_id]
            
            if removed > 0:
                logger.info(f"🧹 Cleaned {removed} expired compliance states")
                self._save_to_disk()
                    
    def get_all_states(self) -> Dict:
        """Get all current states for debugging/export."""
        with self._lock:
            return {
                person_id: {
                    rule_hash: {
                        "status": state.status,
                        "last_verified": state.last_verified.isoformat() if state.last_verified else None,
                        "expires_at": state.expires_at.isoformat() if state.expires_at else None,
                    }
                    for rule_hash, state in person_states.items()
                }
                for person_id, person_states in self.states.items()
            }
        
    def import_states(self, states_dict: Dict):
        """Import states from a dictionary (for session continuity / loading from disk)."""
        with self._lock:
            for person_id, person_states in states_dict.items():
                if person_id not in self.states:
                    self.states[person_id] = {}
                for rule_hash, state_data in person_states.items():
                    self.states[person_id][rule_hash] = ChecklistState(
                        rule_id=rule_hash,
                        person_id=person_id,
                        status=state_data.get("status", "pending"),
                        last_verified=datetime.fromisoformat(state_data["last_verified"]) 
                            if state_data.get("last_verified") else None,
                        expires_at=datetime.fromisoformat(state_data["expires_at"])
                            if state_data.get("expires_at") else None,
                    )
    
    def reset(self):
        """Clear all compliance state (for testing or manual reset)."""
        with self._lock:
            self.states.clear()
            self._save_to_disk()
            logger.info("🔄 Compliance state reset")


# Global instance for the application
compliance_tracker = ComplianceStateTracker()