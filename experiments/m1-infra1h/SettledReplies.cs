using System.Text.Json;
using Sts2Headless;

namespace OfflineSearchHarness;

// Only immutable terminal and pre-draw C replies. These returns precede
// legacy prefix insertion and cannot change the logical 48-slot cache.
internal sealed partial class FirstWin
{
    private readonly Dictionary<string,JsonElement> settledReplies=new(StringComparer.Ordinal);
    private object SaveSettled(string key,object reply,bool last){
        if(last){
            if(settledReplies.Count>=256)settledReplies.Remove(settledReplies.Keys.First());
            settledReplies[key]=JsonSerializer.SerializeToElement(reply,Program.JsonOpts);
        }
        return reply;
    }
    private object? ReadSettled(string key,int calls){
        if(!settledReplies.TryGetValue(key,out var item))return null;
        EngineCounts.SettledHits++;
        return new{kind=item.GetProperty("kind"),state=item.GetProperty("state"),calls};
    }
}
