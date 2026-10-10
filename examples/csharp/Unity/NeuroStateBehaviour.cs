using NeuroState;
using UnityEngine;

/// <summary>
/// Add this to a GameObject to read neurostate values in Unity. Needs the LSL4Unity package
/// and NeuroStateClient.cs in your project (see examples/csharp/README.md).
/// </summary>
public class NeuroStateBehaviour : MonoBehaviour
{
    [Tooltip("Used for attention and relaxation whenever the state isn't ok.")]
    public float neutralValue = 50f;

    // Read these from your own scripts.
    public float Attention { get; private set; }
    public float Relaxation { get; private set; }
    public string State { get; private set; } = "no_signal";

    NeuroStateClient client;

    void OnEnable()
    {
        client = new NeuroStateClient();
        Attention = Relaxation = neutralValue;
    }

    void OnDisable()
    {
        client.Dispose();
        client = null;
    }

    void Update()
    {
        bool fresh = client.TryGetLatest(out BrainState latest);
        State = fresh ? latest.State : "no_signal";
        bool ok = fresh && latest.IsOk;
        Attention = ok ? latest.Attention : neutralValue;
        Relaxation = ok ? latest.Relaxation : neutralValue;
    }
}
