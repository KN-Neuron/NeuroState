# C# client (.NET and Unity)

[NeuroStateClient.cs](NeuroStateClient.cs) reads the neurostate LSL stream on a background
thread and keeps the latest values for your code to pick up. It has no dependencies beyond the
official C# binding for LSL, and is written in C# 8 so Unity 2020.3 and newer can compile it.

```csharp
using var client = new NeuroStateClient();
// ... then, for example once per frame:
if (client.TryGetLatest(out BrainState s) && s.IsOk)
    UseValues(s.Attention, s.Relaxation);
else
    UseValues(50, 50);  // neutral while the signal can't be trusted
```

`TryGetLatest` returns false if no value arrived in the last 2 seconds, for example because
the service isn't running.

## Console demo

Needs the [.NET SDK](https://dotnet.microsoft.com/download) 8 or newer.

```sh
uv run neurostate run --fake          # in one terminal
dotnet run --project examples/csharp  # in another
```

The first build downloads `LSL.cs` (the official binding, pinned to a commit) and the
`SharpLSL.Native.all` NuGet package, which provides the native `liblsl` library for Windows,
macOS and Linux.

## Unity

1. Install the LSL4Unity package. In the Package Manager window, click **+**, choose **Add
   package from git URL...** and enter `https://github.com/labstreaminglayer/LSL4Unity.git`.
   It provides `LSL.cs` and the native libraries.
2. Copy `NeuroStateClient.cs` and `Unity/NeuroStateBehaviour.cs` into your `Assets` folder.
   Don't copy `obj/lsl/LSL.cs`, which LSL4Unity already provides.
3. Add the `NeuroStateBehaviour` component to a GameObject, and read its `Attention`,
   `Relaxation` and `State` properties from your scripts. Attention and relaxation stay at
   `neutralValue` whenever the state isn't `ok`.

`NeuroStateBehaviour.cs` has been compiled against a stand-in for `UnityEngine`, but not yet
run inside Unity.
