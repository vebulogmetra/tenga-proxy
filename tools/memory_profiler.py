#!/usr/bin/env python3
import gc
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

def format_bytes(bytes_count: int) -> str:
    """Format bytes to human-readable string."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    if bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    if bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f} MB"
    return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"


def get_memory_snapshot() -> dict[str, int]:
    """Get current memory snapshot."""
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')

    total_size = sum(stat.size for stat in top_stats)
    total_count = sum(stat.count for stat in top_stats)

    return {
        'total_size': total_size,
        'total_count': total_count,
        'top_stats': top_stats[:20]
    }


def analyze_memory_growth(snapshots: list[tuple[float, dict[str, int]]]) -> None:
    """Analyze memory growth over time."""
    if len(snapshots) < 2:
        print("Not enough snapshots for analysis")
        return

    print("\n" + "="*80)
    print("MEMORY GROWTH ANALYSIS")
    print("="*80)

    initial = snapshots[0][1]
    final = snapshots[-1][1]

    growth = final['total_size'] - initial['total_size']
    growth_percent = (growth / initial['total_size'] * 100) if initial['total_size'] > 0 else 0

    print(f"\nInitial memory: {format_bytes(initial['total_size'])}")
    print(f"Final memory: {format_bytes(final['total_size'])}")
    print(f"Growth: {format_bytes(growth)} ({growth_percent:+.2f}%)")

    if growth > 10 * 1024 * 1024:
        print("\nWARNING: Significant memory growth detected!")
        print("This may indicate a memory leak.")
    elif growth > 0:
        print("\nNOTE: Small memory growth detected.")
        print("This might be normal (caching, etc.) but should be monitored.")
    else:
        print("\n✓ No significant memory growth detected.")

    if len(snapshots) >= 3:
        time_diffs = []
        size_diffs = []
        for i in range(1, len(snapshots)):
            time_diff = snapshots[i][0] - snapshots[i-1][0]
            size_diff = snapshots[i][1]['total_size'] - snapshots[i-1][1]['total_size']
            time_diffs.append(time_diff)
            size_diffs.append(size_diff)

        avg_growth_rate = sum(size_diffs) / sum(time_diffs) if sum(time_diffs) > 0 else 0
        print(f"\nAverage growth rate: {format_bytes(avg_growth_rate)}/second")

        if avg_growth_rate > 1024 * 1024:
            print("WARNING: High memory growth rate detected!")


def print_top_allocations(snapshot: dict[str, int], title: str = "TOP ALLOCATIONS") -> None:
    """Print top memory allocations."""
    print(f"\n{title}")
    print("-" * 80)
    print(f"{'Size':<12} {'Count':<10} {'Location'}")
    print("-" * 80)

    for stat in snapshot['top_stats']:
        size_str = format_bytes(stat.size)
        print(f"{size_str:<12} {stat.count:<10} {stat.traceback.format()[0]}")


def profile_imports() -> dict[str, int]:
    """Profile memory usage after importing main modules."""
    print("="*80)
    print("PROFILING MODULE IMPORTS")
    print("="*80)

    tracemalloc.start()

    snapshots = []

    gc.collect()
    snapshots.append(("baseline", get_memory_snapshot()))

    print("\n1. Importing core modules...")
    import src.core.config
    import src.core.context
    gc.collect()
    snapshots.append(("core", get_memory_snapshot()))

    print("2. Importing database modules...")
    import src.db.data_store
    import src.db.profiles
    gc.collect()
    snapshots.append(("db", get_memory_snapshot()))

    print("3. Importing UI modules...")
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gdk, GLib, Gtk

        import src.ui.app
        import src.ui.main_window
        import src.ui.tray
        gc.collect()
        snapshots.append(("ui", get_memory_snapshot()))
    except (ImportError, ValueError) as e:
        print(f"   Warning: GTK not available ({e}), skipping UI modules")
        snapshots.append(("ui (skipped)", snapshots[-1][1]))

    print("4. Importing singbox manager...")
    gc.collect()
    snapshots.append(("singbox", get_memory_snapshot()))

    print("\n" + "="*80)
    print("MEMORY USAGE BY MODULE")
    print("="*80)

    for i in range(1, len(snapshots)):
        prev = snapshots[i-1][1]
        curr = snapshots[i][1]
        diff = curr['total_size'] - prev['total_size']
        print(f"\n{snapshots[i][0]}: +{format_bytes(diff)} (total: {format_bytes(curr['total_size'])})")

    print_top_allocations(snapshots[-1][1], "TOP ALLOCATIONS AFTER ALL IMPORTS")

    return snapshots[-1][1]


def profile_application_lifecycle() -> None:
    """Profile memory during application lifecycle simulation."""
    print("\n" + "="*80)
    print("PROFILING APPLICATION LIFECYCLE")
    print("="*80)

    try:
        tracemalloc.start()
        snapshots = []

        print("\n1. Initializing application context...")
        from src.core.context import init_context
        context = init_context()
        gc.collect()
        snapshots.append((time.time(), get_memory_snapshot()))

        print("2. Loading profiles...")
        profiles = context.profiles
        profiles.load()
        gc.collect()
        snapshots.append((time.time(), get_memory_snapshot()))

        print("3. Creating singbox manager...")
        manager = context.singbox_manager
        gc.collect()
        snapshots.append((time.time(), get_memory_snapshot()))

        print("4. Simulating connect/disconnect cycles...")
        for cycle in range(5):
            print(f"   Cycle {cycle + 1}/5...")
            context.proxy_state.set_running(1)
            time.sleep(0.1)
            context.proxy_state.set_stopped()
            gc.collect()
            snapshots.append((time.time(), get_memory_snapshot()))

        analyze_memory_growth(snapshots)
        print_top_allocations(snapshots[-1][1], "TOP ALLOCATIONS AFTER LIFECYCLE")
    except Exception as e:
        print(f"Error during lifecycle profiling: {e}")
        import traceback
        traceback.print_exc()


def check_object_counts() -> None:
    """Check counts of various object types."""
    print("\n" + "="*80)
    print("OBJECT COUNTS")
    print("="*80)

    import gc
    from collections import Counter

    objects = gc.get_objects()
    types = Counter(type(obj).__name__ for obj in objects)

    print("\nTop 20 object types by count:")
    print("-" * 80)
    print(f"{'Type':<40} {'Count':<10}")
    print("-" * 80)

    for obj_type, count in types.most_common(20):
        print(f"{obj_type:<40} {count:<10}")

    print(f"\nTotal objects: {len(objects)}")


def main():
    """Main profiling function."""
    print("="*80)
    print("TENGA PROXY MEMORY PROFILER")
    print("="*80)

    final_snapshot = profile_imports()
    check_object_counts()
    profile_application_lifecycle()

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total tracked memory: {format_bytes(final_snapshot['total_size'])}")
    print(f"Total allocations: {final_snapshot['total_count']:,}")

    tracemalloc.stop()


if __name__ == "__main__":
    main()
