#!/usr/bin/env python3
"""
Training Data Review Tool
Interactive CLI for labeling classification decisions
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter


class ThreatReviewer:
    """Interactive tool for reviewing and labeling threat classifications"""

    def __init__(self, data_dir="/home/hashcat/pfsense/ai_suricata/training_data"):
        self.data_dir = Path(data_dir)
        self.examples = []
        self.current_index = 0
        self.session_labels = 0

        # Color codes for terminal output
        self.COLORS = {
            'RED': '\033[91m',
            'GREEN': '\033[92m',
            'YELLOW': '\033[93m',
            'BLUE': '\033[94m',
            'MAGENTA': '\033[95m',
            'CYAN': '\033[96m',
            'WHITE': '\033[97m',
            'BOLD': '\033[1m',
            'RESET': '\033[0m'
        }

    def color(self, text, color_name):
        """Apply color to text"""
        return f"{self.COLORS.get(color_name, '')}{text}{self.COLORS['RESET']}"

    def load_data(self, since_hours=24, severity_filter=None, action_filter=None, unlabeled_only=True):
        """Load training data from JSONL files"""
        cutoff_time = datetime.now() - timedelta(hours=since_hours) if since_hours else None

        print(f"[*] Loading training data from {self.data_dir}")

        log_files = sorted(self.data_dir.glob("decisions.*.jsonl"))
        if not log_files:
            print(f"[!] No training data found in {self.data_dir}")
            print(f"[*] Data collection starts after service restart")
            return 0

        loaded_count = 0
        for log_file in log_files:
            with open(log_file, 'r') as f:
                for line in f:
                    try:
                        example = json.loads(line.strip())

                        # Time filter
                        if cutoff_time:
                            example_time = datetime.fromisoformat(example['timestamp'].replace('Z', '+00:00'))
                            if example_time < cutoff_time:
                                continue

                        # Severity filter
                        if severity_filter:
                            if example['classification']['severity'] not in severity_filter:
                                continue

                        # Action filter
                        if action_filter:
                            if example['classification']['action'] not in action_filter:
                                continue

                        # Unlabeled only filter
                        if unlabeled_only and example.get('label') is not None:
                            continue

                        self.examples.append({
                            'data': example,
                            'file': log_file
                        })
                        loaded_count += 1

                    except json.JSONDecodeError:
                        continue

        print(f"[+] Loaded {loaded_count} examples for review")
        return loaded_count

    def display_example(self, index):
        """Display a single example for review"""
        if index >= len(self.examples):
            return False

        example = self.examples[index]['data']
        classification = example['classification']

        # Clear screen (works on most terminals)
        print("\033[2J\033[H")

        # Header
        print(self.color("=" * 80, 'CYAN'))
        print(self.color(f"  THREAT REVIEW - Example {index + 1} / {len(self.examples)}", 'CYAN'))
        print(self.color("=" * 80, 'CYAN'))
        print()

        # Timestamp
        print(f"{self.color('Timestamp:', 'BOLD')} {example['timestamp']}")
        print()

        # Source/Dest
        print(f"{self.color('Source IP:', 'BOLD')} {self.color(example['source_ip'], 'YELLOW')}")
        print(f"{self.color('Dest IP:', 'BOLD')}   {example['dest_ip']}")
        print()

        # Signature
        sig = example['signature']
        sig_color = 'RED' if 'exploit' in sig.lower() or 'malware' in sig.lower() else 'WHITE'
        print(f"{self.color('Signature:', 'BOLD')} {self.color(sig, sig_color)}")
        print(f"{self.color('Category:', 'BOLD')}  {example.get('category', 'Unknown')}")
        print()

        # ML Classification
        severity = classification['severity']
        threat_score = classification['threat_score']
        action = classification['action']

        severity_colors = {
            'CRITICAL': 'RED',
            'HIGH': 'YELLOW',
            'MEDIUM': 'MAGENTA',
            'LOW': 'BLUE',
            'INFO': 'WHITE'
        }

        print(self.color("ML Classification:", 'BOLD'))
        print(f"  Severity:     {self.color(severity, severity_colors.get(severity, 'WHITE'))}")
        print(f"  Threat Score: {self.color(f'{threat_score:.3f}', 'YELLOW')}")
        print(f"  Action:       {self.color(action, 'GREEN' if action == 'LOG' else 'RED')}")
        print()

        # Score Breakdown
        print(self.color("Score Breakdown:", 'BOLD'))
        print(f"  Base Score:    {classification['base_score']:.3f} (30% weight)")
        print(f"  Anomaly Score: {classification['anomaly_score']:.3f} (30% weight)")
        print(f"  Pattern Score: {classification['pattern_score']:.3f} (40% weight)")
        print()

        # Attack Patterns
        patterns = classification.get('patterns_detected', [])
        if patterns:
            print(self.color("Attack Patterns Detected:", 'BOLD'))
            for pattern in patterns:
                pattern_name = pattern.get('pattern', 'unknown')
                confidence = pattern.get('confidence', 0.0)
                details = pattern.get('details', '')
                print(f"  • {self.color(pattern_name.upper(), 'RED')} (confidence: {confidence:.2f})")
                print(f"    {details}")
            print()

        # Feature Highlights
        features = example.get('features', {})
        print(self.color("Key Features:", 'BOLD'))
        print(f"  Src Port: {int(features.get('src_port', 0)):5d}  "
              f"Dest Port: {int(features.get('dest_port', 0)):5d}  "
              f"IP Alert Count: {int(features.get('ip_alert_count', 0))}")
        print(f"  Packets: ↑{int(features.get('packets_toserver', 0))} ↓{int(features.get('packets_toclient', 0))}  "
              f"Bytes: ↑{int(features.get('bytes_toserver', 0))} ↓{int(features.get('bytes_toclient', 0))}")
        print()

        # Auto-label hint
        auto_hint = example.get('auto_label_hint', 'REVIEW')
        hint_color = {
            'BENIGN': 'GREEN',
            'THREAT': 'RED',
            'REVIEW': 'YELLOW'
        }.get(auto_hint, 'WHITE')

        print(f"{self.color('Auto-Label Hint:', 'BOLD')} {self.color(auto_hint, hint_color)}")
        print()

        # Current label (if any)
        if example.get('label'):
            print(f"{self.color('Current Label:', 'BOLD')} {self.color(example['label'], 'GREEN')}")
            print(f"  Labeled by: {example.get('labeled_by', 'unknown')}")
            print(f"  Labeled at: {example.get('labeled_at', 'unknown')}")
            if example.get('notes'):
                print(f"  Notes: {example['notes']}")
            print()

        return True

    def get_user_input(self):
        """Get labeling decision from user"""
        print(self.color("─" * 80, 'CYAN'))
        print()
        print("Is this a REAL THREAT?")
        print()
        print(f"  {self.color('[T]', 'RED')}hreat      - Confirmed malicious activity")
        print(f"  {self.color('[B]', 'GREEN')}enign      - Legitimate traffic (false positive)")
        print(f"  {self.color('[F]', 'YELLOW')}alse_Pos   - ML incorrectly classified as threat")
        print(f"  {self.color('[S]', 'BLUE')}kip        - Skip this one (review later)")
        print(f"  {self.color('[N]', 'MAGENTA')}ext        - Skip and don't ask again")
        print(f"  {self.color('[Q]', 'WHITE')}uit        - Save and exit")
        print()

        while True:
            try:
                choice = input(self.color("Your choice: ", 'BOLD')).strip().upper()

                if choice in ['T', 'B', 'F', 'S', 'N', 'Q']:
                    return choice
                else:
                    print(self.color("Invalid choice. Please enter T, B, F, S, N, or Q.", 'RED'))
            except (KeyboardInterrupt, EOFError):
                return 'Q'

    def label_example(self, index, label, notes=None):
        """Apply label to an example and update the file"""
        if index >= len(self.examples):
            return False

        example_entry = self.examples[index]
        example = example_entry['data']
        log_file = example_entry['file']

        # Update example with label
        label_map = {
            'T': 'THREAT',
            'B': 'BENIGN',
            'F': 'FALSE_POSITIVE'
        }

        example['label'] = label_map.get(label, label)
        example['labeled_by'] = 'human_review'
        example['labeled_at'] = datetime.now().isoformat()
        if notes:
            example['notes'] = notes

        # Read all examples from the file
        with open(log_file, 'r') as f:
            lines = f.readlines()

        # Update the specific line
        # Find the line by matching timestamp and source_ip
        updated = False
        for i, line in enumerate(lines):
            try:
                line_data = json.loads(line.strip())
                if (line_data.get('timestamp') == example['timestamp'] and
                    line_data.get('source_ip') == example['source_ip']):
                    lines[i] = json.dumps(example) + '\n'
                    updated = True
                    break
            except json.JSONDecodeError:
                continue

        # Write back to file
        if updated:
            with open(log_file, 'w') as f:
                f.writelines(lines)
            return True

        return False

    def review_loop(self):
        """Main interactive review loop"""
        if not self.examples:
            print("[!] No examples to review")
            return

        self.current_index = 0

        while self.current_index < len(self.examples):
            if not self.display_example(self.current_index):
                break

            choice = self.get_user_input()

            if choice == 'Q':
                print()
                print(self.color(f"[+] Session complete! Labeled {self.session_labels} examples.", 'GREEN'))
                break
            elif choice == 'S':
                # Skip - move to next
                self.current_index += 1
            elif choice == 'N':
                # Next - mark as skipped and move on
                self.current_index += 1
            elif choice in ['T', 'B', 'F']:
                # Label and move to next
                notes = None

                # Optionally ask for notes on important labels
                if choice in ['T', 'F']:
                    print()
                    note_input = input(self.color("Add notes (optional, press Enter to skip): ", 'YELLOW'))
                    if note_input.strip():
                        notes = note_input.strip()

                if self.label_example(self.current_index, choice, notes):
                    print()
                    print(self.color("[+] Labeled and saved!", 'GREEN'))
                    self.session_labels += 1
                    import time
                    time.sleep(0.5)  # Brief pause for feedback
                else:
                    print()
                    print(self.color("[!] Failed to save label", 'RED'))
                    import time
                    time.sleep(1)

                self.current_index += 1

        # Final statistics
        self.show_statistics()

    def show_statistics(self):
        """Display labeling statistics"""
        if not self.examples:
            return

        print()
        print(self.color("=" * 80, 'CYAN'))
        print(self.color("  LABELING STATISTICS", 'CYAN'))
        print(self.color("=" * 80, 'CYAN'))
        print()

        # Count labels
        label_counts = Counter()
        unlabeled = 0

        for entry in self.examples:
            label = entry['data'].get('label')
            if label:
                label_counts[label] += 1
            else:
                unlabeled += 1

        total = len(self.examples)
        labeled = total - unlabeled

        print(f"Total Examples:     {total}")
        print(f"Labeled:            {labeled} ({labeled/total*100:.1f}%)")
        print(f"Unlabeled:          {unlabeled} ({unlabeled/total*100:.1f}%)")
        print()

        if label_counts:
            print("Label Distribution:")
            for label, count in label_counts.most_common():
                color = {
                    'THREAT': 'RED',
                    'BENIGN': 'GREEN',
                    'FALSE_POSITIVE': 'YELLOW'
                }.get(label, 'WHITE')
                print(f"  {self.color(label, color):20s} {count:5d} ({count/labeled*100:.1f}%)")

        print()
        print(f"Session Labels:     {self.session_labels}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description='Review and label ML classification decisions for training',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review HIGH and CRITICAL alerts from last 24 hours
  %(prog)s --severity HIGH,CRITICAL --since 24

  # Review all blocked IPs
  %(prog)s --action BLOCK --since 168

  # Review everything (including already labeled)
  %(prog)s --all --since 720

  # Show statistics only
  %(prog)s --stats-only
        """
    )

    parser.add_argument('--since', type=int, default=24,
                       help='Review alerts from last N hours (default: 24)')

    parser.add_argument('--severity', type=str,
                       help='Filter by severity (comma-separated): CRITICAL,HIGH,MEDIUM,LOW,INFO')

    parser.add_argument('--action', type=str,
                       help='Filter by action (comma-separated): BLOCK,RATE_LIMIT,MONITOR,LOG')

    parser.add_argument('--all', action='store_true',
                       help='Include already labeled examples')

    parser.add_argument('--stats-only', action='store_true',
                       help='Show statistics only, no interactive review')

    parser.add_argument('--data-dir', type=str,
                       default='/home/hashcat/pfsense/ai_suricata/training_data',
                       help='Training data directory')

    args = parser.parse_args()

    # Parse filters
    severity_filter = args.severity.split(',') if args.severity else None
    action_filter = args.action.split(',') if args.action else None

    # Create reviewer
    reviewer = ThreatReviewer(data_dir=args.data_dir)

    # Load data
    count = reviewer.load_data(
        since_hours=args.since,
        severity_filter=severity_filter,
        action_filter=action_filter,
        unlabeled_only=not args.all
    )

    if count == 0:
        print("[*] No examples match your filters")
        return 0

    # Stats only mode
    if args.stats_only:
        reviewer.show_statistics()
        return 0

    # Interactive review
    try:
        reviewer.review_loop()
    except KeyboardInterrupt:
        print()
        print("\n[!] Review interrupted by user")
        reviewer.show_statistics()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
