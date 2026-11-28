using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;

using var stream = File.OpenRead(args[0]);
using var pe = new PEReader(stream);
var md = pe.GetMetadataReader();
var rows = new List<object>();
foreach (var handle in md.TypeDefinitions) {
    var t = md.GetTypeDefinition(handle);
    var ns = md.GetString(t.Namespace);
    var name = md.GetString(t.Name);
    if (name.Contains("MultiplayerConstraint")) {
        foreach (var field in t.GetFields()) {
            var f = md.GetFieldDefinition(field);
            var value = f.GetDefaultValue();
            if (!value.IsNil) rows.Add(new {type=name,field=md.GetString(f.Name),constant=Convert.ToHexString(md.GetBlobBytes(md.GetConstant(value).Value))});
        }
    }
    if (!ns.Contains("Models.Cards") && name!="CardModel") continue;
    foreach (var mh in t.GetMethods()) {
        var m=md.GetMethodDefinition(mh);
        var method=md.GetString(m.Name);
        if (method.Contains("Multiplayer") && m.RelativeVirtualAddress!=0)
            rows.Add(new {type=name,method,il=Convert.ToHexString(pe.GetMethodBody(m.RelativeVirtualAddress).GetILBytes()!)});
    }
}
Console.WriteLine(JsonSerializer.Serialize(rows));
