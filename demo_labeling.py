#!/usr/bin/env python3
"""
Automated Labeling Demo
Demonstrates the labeling workflow by auto-labeling sample data
"""

import json
from pathlib import Path
from datetime import datetime
import time

# Colors for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def print_header(text):
    print(f"\n{Colors.CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}  {text}{Colors.RESET}")
    print(f"{Colors.CYAN}{'=' * 80}{Colors.RESET}\n")

def print_example(example, index, total):
    """Display an example in the same format as the review tool"""
    cls = example['classification']
    features = example['features']

    print(f"{Colors.BOLD}[Example {index}/{total}]{Colors.RESET}")
    print(f"  Time: {example['timestamp']}")
    print(f"  Source: {Colors.YELLOW}{example['source_ip']}{Colors.RESET}")
    print(f"  Threat Score: {Colors.YELLOW}{cls['threat_score']:.3f}{Colors.RESET}")
    print(f"  Severity: {Colors.BLUE}{cls['severity']}{Colors.RESET}")
    print(f"  Action: {cls['action']}")
    print(f"  Src Port: {int(features['src_port'])} → Dest Port: {int(features['dest_port'])}")
    print()

def auto_label_example(example):
    """Automatically determine label based on simple heuristics"""
    score = example['classification']['threat_score']
    severity = example['classification']['severity']
    signature = example['signature'].lower()

    # Auto-labeling logic
    if severity == 'CRITICAL' or score >= 0.85:
        return 'THREAT', 'High threat score or critical severity'
    elif 'checksum' in signature or 'invalid ack' in signature:
        return 'BENIGN', 'Network protocol artifact'
    elif severity == 'LOW' and score < 0.5:
        return 'BENIGN', 'Low threat score, normal traffic'
    else:
        return 'BENIGN', 'Default: benign classification'

def main():
    data_file = Path('/home/hashcat/pfsense/ai_suricata/training_data/decisions.2025-12-23.jsonl')

    if not data_file.exists():
        print(f"{Colors.RED}[!] No training data found{Colors.RESET}")
        return

    print_header("AUTOMATED LABELING DEMO")

    print(f"{Colors.BOLD}This demo will:{Colors.RESET}")
    print(f"  1. Load training examples")
    print(f"  2. Automatically label 10 examples")
    print(f"  3. Save labels to the data file")
    print(f"  4. Show before/after statistics")
    print()

    input(f"{Colors.GREEN}Press Enter to start...{Colors.RESET}")

    # Load all examples
    print(f"\n{Colors.BOLD}[*] Loading training data...{Colors.RESET}")
    examples = []
    with open(data_file, 'r') as f:
        for line in f:
            examples.append(json.loads(line.strip()))

    print(f"{Colors.GREEN}[+] Loaded {len(examples):,} examples{Colors.RESET}")

    # Count unlabeled
    unlabeled = [ex for ex in examples if ex.get('label') is None]
    print(f"{Colors.YELLOW}[*] {len(unlabeled):,} unlabeled examples{Colors.RESET}")

    # Select 10 random unlabeled examples
    import random
    sample_size = min(10, len(unlabeled))
    samples = random.sample(unlabeled, sample_size)

    print_header("LABELING EXAMPLES")

    labeled_count = 0
    labels = []

    for i, example in enumerate(samples, 1):
        print_example(example, i, sample_size)

        # Auto-label
        label, reason = auto_label_example(example)

        print(f"{Colors.BOLD}  Decision: {Colors.GREEN if label == 'BENIGN' else Colors.RED}{label}{Colors.RESET}")
        print(f"{Colors.BOLD}  Reason: {Colors.RESET}{reason}")
        print()

        # Apply label
        example['label'] = label
        example['labeled_by'] = 'automated_demo'
        example['labeled_at'] = datetime.now().isoformat()
        example['notes'] = reason

        labels.append(label)
        labeled_count += 1

        # Simulate human review time
        time.sleep(0.3)

        if i % 3 == 0:
            print(f"{Colors.CYAN}  [{i}/{sample_size} labeled...]{Colors.RESET}\n")

    # Save back to file
    print(f"\n{Colors.BOLD}[*] Saving labels to file...{Colors.RESET}")

    with open(data_file, 'w') as f:
        for ex in examples:
            f.write(json.dumps(ex) + '\n')

    print(f"{Colors.GREEN}[+] Labels saved!{Colors.RESET}")

    # Show statistics
    print_header("LABELING STATISTICS")

    # Count all labels
    all_labels = {}
    total_labeled = 0
    for ex in examples:
        if ex.get('label'):
            total_labeled += 1
            label = ex['label']
            all_labels[label] = all_labels.get(label, 0) + 1

    print(f"{Colors.BOLD}Total Examples:{Colors.RESET}     {len(examples):,}")
    print(f"{Colors.BOLD}Labeled:{Colors.RESET}            {total_labeled} ({total_labeled/len(examples)*100:.1f}%)")
    print(f"{Colors.BOLD}Unlabeled:{Colors.RESET}          {len(examples) - total_labeled} ({(len(examples) - total_labeled)/len(examples)*100:.1f}%)")
    print()

    if all_labels:
        print(f"{Colors.BOLD}Label Distribution:{Colors.RESET}")
        for label, count in sorted(all_labels.items(), key=lambda x: x[1], reverse=True):
            color = Colors.GREEN if label == 'BENIGN' else Colors.RED
            pct = count / total_labeled * 100
            print(f"  {color}{label:15s}{Colors.RESET}  {count:5d} ({pct:5.1f}%)")

    print(f"\n{Colors.BOLD}Session Labels:{Colors.RESET}     {labeled_count}")
    print()

    # Summary
    print_header("DEMO COMPLETE")

    print(f"{Colors.GREEN}✓{Colors.RESET} Successfully labeled {labeled_count} examples")
    print(f"{Colors.GREEN}✓{Colors.RESET} Labels saved to: {data_file.name}")
    print(f"{Colors.GREEN}✓{Colors.RESET} Total labeled so far: {total_labeled}/{len(examples)}")
    print()

    print(f"{Colors.BOLD}What happened:{Colors.RESET}")
    print(f"  1. Loaded {len(examples):,} training examples")
    print(f"  2. Selected {sample_size} random unlabeled examples")
    print(f"  3. Auto-labeled them as: {dict([(l, labels.count(l)) for l in set(labels)])}")
    print(f"  4. Saved labels back to the JSONL file")
    print()

    print(f"{Colors.BOLD}Next steps:{Colors.RESET}")
    print(f"  • Run: {Colors.CYAN}./review_threats.py --stats-only{Colors.RESET}")
    print(f"  • Review more: {Colors.CYAN}./review_threats.py --severity LOW{Colors.RESET}")
    print(f"  • Check labeled data: {Colors.CYAN}grep '\"label\": \"' training_data/*.jsonl | wc -l{Colors.RESET}")
    print()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}[!] Demo interrupted{Colors.RESET}")
    except Exception as e:
        print(f"\n{Colors.RED}[!] Error: {e}{Colors.RESET}")
