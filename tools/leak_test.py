#!/usr/bin/env python3
import sys
import time
import gc
import tracemalloc
import psutil
import os
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))


def format_bytes(bytes_count: int) -> str:
    """Format bytes to human-readable string."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    elif bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"


def get_process_memory() -> int:
    """Get current process memory usage in bytes."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss


def simulate_application_usage(context, iterations: int = 100, interval: float = 0.1) -> List[Tuple[float, int, int]]:
    """Simulate application usage and track memory."""
    print(f"\nSimulating {iterations} iterations with {interval}s interval...")
    
    measurements = []
    tracemalloc.start()
    
    for i in range(iterations):
        if i % 2 == 0:
            context.proxy_state.set_running(1)
        else:
            context.proxy_state.set_stopped()

        if i % 10 == 0:
            gc.collect()
        
        if i % 5 == 0:
            process_mem = get_process_memory()
            snapshot = tracemalloc.take_snapshot()
            tracked_mem = sum(stat.size for stat in snapshot.statistics('lineno'))
            measurements.append((time.time(), process_mem, tracked_mem))
            
            if i % 20 == 0:
                print(f"  Iteration {i}/{iterations}: "
                      f"Process={format_bytes(process_mem)}, "
                      f"Tracked={format_bytes(tracked_mem)}")
        
        time.sleep(interval)
    
    tracemalloc.stop()
    return measurements


def analyze_leak(measurements: List[Tuple[float, int, int]]) -> None:
    """Analyze measurements for memory leaks."""
    if len(measurements) < 2:
        print("Not enough measurements")
        return
    
    print("\n" + "="*80)
    print("MEMORY LEAK ANALYSIS")
    print("="*80)
    
    initial_process = measurements[0][1]
    final_process = measurements[-1][1]
    process_growth = final_process - initial_process
    
    initial_tracked = measurements[0][2]
    final_tracked = measurements[-1][2]
    tracked_growth = final_tracked - initial_tracked
    
    print(f"\nProcess Memory (RSS):")
    print(f"  Initial: {format_bytes(initial_process)}")
    print(f"  Final: {format_bytes(final_process)}")
    print(f"  Growth: {format_bytes(process_growth)} "
          f"({process_growth / initial_process * 100:+.2f}%)")
    
    print(f"\nTracked Memory (tracemalloc):")
    print(f"  Initial: {format_bytes(initial_tracked)}")
    print(f"  Final: {format_bytes(final_tracked)}")
    print(f"  Growth: {format_bytes(tracked_growth)} "
          f"({tracked_growth / initial_tracked * 100:+.2f}%)")
    
    time_span = measurements[-1][0] - measurements[0][0]
    process_rate = process_growth / time_span if time_span > 0 else 0
    tracked_rate = tracked_growth / time_span if time_span > 0 else 0
    
    print(f"\nGrowth Rate:")
    print(f"  Process: {format_bytes(process_rate)}/second")
    print(f"  Tracked: {format_bytes(tracked_rate)}/second")
    
    leak_threshold = 10 * 1024 * 1024  # 10 MB
    rate_threshold = 100 * 1024  # 100 KB/s
    
    print(f"\n" + "="*80)
    if process_growth > leak_threshold or process_rate > rate_threshold:
        print("WARNING: Potential memory leak detected!")
        print(f"   Process memory grew by {format_bytes(process_growth)}")
        if process_rate > rate_threshold:
            print(f"   Growth rate: {format_bytes(process_rate)}/second (high!)")
    elif process_growth > leak_threshold / 2:
        print("CAUTION: Moderate memory growth detected")
        print(f"   Process memory grew by {format_bytes(process_growth)}")
        print("   This might be normal but should be monitored.")
    else:
        print("No significant memory leak detected")
        print(f"   Memory growth: {format_bytes(process_growth)} (acceptable)")
    print("="*80)


def test_listener_leak(context, iterations: int = 50) -> None:
    """Test for listener leaks by creating and destroying windows."""
    print("\n" + "="*80)
    print("TESTING LISTENER LEAKS")
    print("="*80)
    
    tracemalloc.start()
    initial_snapshot = tracemalloc.take_snapshot()
    initial_mem = get_process_memory()
    
    for i in range(iterations):
        def listener(state):
            pass
        
        context.proxy_state.add_listener(listener)
        
        context.proxy_state.remove_listener(listener)
        
        if i % 10 == 0:
            gc.collect()
    
    gc.collect()
    final_snapshot = tracemalloc.take_snapshot()
    final_mem = get_process_memory()
    
    tracemalloc.stop()
    
    initial_tracked = sum(stat.size for stat in initial_snapshot.statistics('lineno'))
    final_tracked = sum(stat.size for stat in final_snapshot.statistics('lineno'))
    
    print(f"Initial memory: {format_bytes(initial_mem)}")
    print(f"Final memory: {format_bytes(final_mem)}")
    print(f"Growth: {format_bytes(final_mem - initial_mem)}")
    print(f"\nTracked memory growth: {format_bytes(final_tracked - initial_tracked)}")
    
    if final_mem - initial_mem > 5 * 1024 * 1024:
        print("\nWARNING: Potential listener leak detected!")
    else:
        print("\nNo listener leak detected")


def main():
    """Main test function."""
    print("="*80)
    print("TENGA PROXY MEMORY LEAK TEST")
    print("="*80)
    
    print("\nInitializing application...")
    from src.core.context import init_context
    
    context = init_context()
    gc.collect()
    
    test_listener_leak(context, iterations=50)
    
    measurements = simulate_application_usage(context, iterations=100, interval=0.1)
    
    analyze_leak(measurements)
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
