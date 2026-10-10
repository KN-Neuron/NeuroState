using System;
using System.Threading;
using LSL;

namespace NeuroState
{
    /// <summary>One update from the neurostate service.</summary>
    public readonly struct BrainState
    {
        public readonly float Attention;   // 0-100
        public readonly float Relaxation;  // 0-100
        public readonly float Quality;     // 0-100; 0 means no usable signal
        public readonly string State;      // no_signal, poor_signal, calibrating, uncalibrated or ok
        public readonly bool Calibrated;
        public readonly double Timestamp;  // LSL clock

        public BrainState(float attention, float relaxation, float quality, string state,
                          bool calibrated, double timestamp)
        {
            Attention = attention;
            Relaxation = relaxation;
            Quality = quality;
            State = state;
            Calibrated = calibrated;
            Timestamp = timestamp;
        }

        /// <summary>Use the values only when this is true; otherwise fall back to a neutral default.</summary>
        public bool IsOk => State == "ok";
    }

    /// <summary>
    /// Reads the NeuroState LSL stream on a background thread, so it never blocks your main or
    /// render loop. It finds the stream whenever it appears and keeps going if the service restarts.
    /// </summary>
    public sealed class NeuroStateClient : IDisposable
    {
        // The state code table, as listed in the stream's metadata (schema version 1).
        static readonly string[] StateNames = { "no_signal", "poor_signal", "calibrating", "uncalibrated", "ok" };

        readonly string streamType;
        readonly double staleAfterSeconds;
        readonly Thread thread;
        readonly object gate = new object();
        volatile bool running = true;
        BrainState latest;
        double lastArrival = double.NegativeInfinity;

        public NeuroStateClient(string streamType = "BrainState", double staleAfterSeconds = 2.0)
        {
            this.streamType = streamType;
            this.staleAfterSeconds = staleAfterSeconds;
            thread = new Thread(Run) { IsBackground = true, Name = "NeuroStateClient" };
            thread.Start();
        }

        /// <summary>
        /// The latest update. Returns false if none arrived in the last staleAfterSeconds, for
        /// example because the service isn't running.
        /// </summary>
        public bool TryGetLatest(out BrainState state)
        {
            lock (gate)
            {
                state = latest;
                return LSL.LSL.local_clock() - lastArrival < staleAfterSeconds;
            }
        }

        void Run()
        {
            var sample = new float[5];
            while (running)
            {
                StreamInfo[] found = LSL.LSL.resolve_stream("type", streamType, 1, 1.0);
                if (found.Length == 0)
                    continue;
                using (var inlet = new StreamInlet(found[0]))
                {
                    while (running)
                    {
                        double timestamp = inlet.pull_sample(sample, 0.5);
                        if (timestamp == 0.0)
                            continue;  // nothing within 0.5 s; the inlet reconnects by itself
                        int code = (int)sample[3];
                        string name = code >= 0 && code < StateNames.Length ? StateNames[code] : "unknown";
                        var state = new BrainState(sample[0], sample[1], sample[2], name, sample[4] > 0.5f, timestamp);
                        lock (gate)
                        {
                            latest = state;
                            lastArrival = LSL.LSL.local_clock();
                        }
                    }
                }
            }
        }

        public void Dispose()
        {
            running = false;
            thread.Join(TimeSpan.FromSeconds(2));
        }
    }
}
