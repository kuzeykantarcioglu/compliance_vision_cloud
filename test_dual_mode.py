#!/usr/bin/env python3
"""
Test script for dual-mode compliance system.
Tests both incident and checklist modes.
"""

import json
import requests
import base64
from datetime import datetime

# API endpoint
API_URL = "http://localhost:8000"

def create_test_image():
    """Use an existing test image if available, otherwise create a minimal one"""
    import os
    
    # Try to use an existing test image
    test_images = [
        "/Users/kuzeykantarcioglu/treehacks2026/keyframes/8c5ab540c3d3/change_0000.jpg",
        "/Users/kuzeykantarcioglu/treehacks2026/keyframes/7b83bcb35bea/change_0000.jpg"
    ]
    
    for img_path in test_images:
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8')
    
    # Fallback: create a minimal valid JPEG
    # This is a 1x1 red JPEG
    minimal_jpeg = (
        "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
        "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
        "AQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCmAA8A"
        "AAD//Z=="
    )
    
    return minimal_jpeg

def test_dual_mode_policy():
    """Test a policy with both incident and checklist mode rules"""
    
    test_policy = {
        "rules": [
            {
                "type": "ppe",
                "description": "Must wear hard hat at all times",
                "severity": "critical",
                "mode": "incident",  # Always alert
            },
            {
                "type": "ppe", 
                "description": "Must show ID badge",
                "severity": "medium",
                "mode": "checklist",  # Check once
                "validity_duration": 300,  # 5 minutes
            },
            {
                "type": "behavior",
                "description": "No running in facility",
                "severity": "high",
                "mode": "incident",  # Always alert
            },
            {
                "type": "presence",
                "description": "Supervisor must be present",
                "severity": "low",
                "mode": "checklist",
                "validity_duration": 3600,  # 1 hour
            }
        ],
        "custom_prompt": "Monitor workplace safety compliance",
        "include_audio": False,
        "reference_images": []
    }
    
    # Create test frame
    frame = create_test_image()
    
    # Prepare request for frame endpoint
    request_data = {
        "image_base64": frame,
        "policy_json": json.dumps(test_policy)
    }
    
    print("Testing dual-mode compliance system...")
    print(f"Policy has {len(test_policy['rules'])} rules:")
    for rule in test_policy['rules']:
        print(f"  - {rule['description']} (mode: {rule.get('mode', 'incident')})")
    print()
    
    try:
        # Send request
        response = requests.post(
            f"{API_URL}/analyze/frame",
            json=request_data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            
            if result["status"] == "complete":
                report = result["report"]
                print(f"✅ Analysis complete!")
                print(f"Overall compliance: {report['overall_compliant']}")
                print(f"Summary: {report['summary']}")
                print()
                
                # Check incidents vs checklist items
                incidents = [v for v in report.get('incidents', []) if v.get('mode') != 'checklist']
                checklist_items = [v for v in report.get('all_verdicts', []) if v.get('mode') == 'checklist']
                
                print(f"Incidents (always alert): {len(incidents)}")
                for inc in incidents:
                    print(f"  - {inc['rule_description']}: {inc['reason']}")
                
                print()
                print(f"Checklist items (check once): {len(checklist_items)}")
                for item in checklist_items:
                    status = item.get('checklist_status', 'unknown')
                    print(f"  - {item['rule_description']}: {status}")
                    if item.get('expires_at'):
                        print(f"    Expires at: {datetime.fromtimestamp(item['expires_at']).isoformat()}")
                
            else:
                print(f"❌ Analysis failed: {result.get('error', 'Unknown error')}")
                
        else:
            print(f"❌ Request failed with status {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_dual_mode_policy()