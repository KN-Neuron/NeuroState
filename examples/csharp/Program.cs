using System;
using System.Threading;
using NeuroState;

// Prints the values twice a second. Start the service first: uv run neurostate run --fake
static class Program
{
    static void Main()
    {
        using var client = new NeuroStateClient();
        using var stop = new ManualResetEventSlim();
        Console.CancelKeyPress += (sender, e) => { e.Cancel = true; stop.Set(); };

        Console.WriteLine("Looking for the NeuroState stream... (Ctrl+C to quit)");
        while (!stop.Wait(500))
        {
            if (client.TryGetLatest(out BrainState s))
                Console.WriteLine($"{s.State,-12}  attention {s.Attention,5:F1}  relaxation {s.Relaxation,5:F1}  quality {s.Quality,3:F0}");
            else
                Console.WriteLine("No values. Is the service running?");
        }
    }
}
