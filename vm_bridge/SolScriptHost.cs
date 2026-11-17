// VM 4.4 SDK adapter. Passwords arrive on stdin only. Never calls Run/SilentExecute.
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

public sealed class SolScriptHost : MarshalByRefObject
{
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 16000000 };
    static string apps;
    static Dictionary<string,string> libs = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
    public class OwnerAdapter : Apps.Interface.IOwner { public object Owner { get; set; } }
    static object Get(object o,string name) { return o.GetType().GetProperty(name).GetValue(o,null); }
    static object Call(object o,string name,params object[] args) {
        return o.GetType().GetMethods().Single(m=>m.Name==name && m.GetParameters().Length==args.Length).Invoke(o,args);
    }
    static object Static(Type t,string name,params object[] args) {
        return t.GetMethods(BindingFlags.Public|BindingFlags.Static).Single(m=>m.Name==name && m.GetParameters().Length==args.Length).Invoke(null,args);
    }
    static void Binary(object module,string key,byte[] bytes) {
        object param=Get(module,"Params");
        param.GetType().GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance)
            .Single(m=>m.Name.EndsWith("set_Item") && m.GetParameters().Length==2 && m.GetParameters()[1].ParameterType==typeof(byte[]))
            .Invoke(param,new object[]{key,bytes});
    }
    static IEnumerable<object> Leaves(object collection) {
        foreach(object io in (IEnumerable)collection) {
            if ((bool)Get(io,"IsLeafNode")) yield return io;
            else foreach(object child in Leaves(Get(io,"Children"))) yield return child;
        }
    }
    static object FindModule(object parent,uint id) {
        PropertyInfo children=parent.GetType().GetProperty("Modules");if(children==null)return null;
        foreach(object module in (IEnumerable)children.GetValue(parent,null)) {
            if(Convert.ToUInt32(Get(module,"ID"))==id)return module;
            object found=FindModule(module,id);if(found!=null)return found;
        }
        return null;
    }
    static string Package(Dictionary<string,object> request) {
        string library=Path.Combine(apps,@"3rdLib\NPOI\ICSharpCode.SharpZipLib.dll");
        Assembly zip=Assembly.LoadFrom(library);
        Type zipType=zip.GetType("ICSharpCode.SharpZipLib.Zip.ZipFile",true);
        Type sourceType=zip.GetType("ICSharpCode.SharpZipLib.Zip.StaticDiskDataSource",true);
        Type zip64Type=zip.GetType("ICSharpCode.SharpZipLib.Zip.UseZip64",true);
        // Obtain the target frame's new compressed/encrypted record using the
        // vendor updater. It still normalizes some untouched entry metadata;
        // Python restores every non-target raw record before final delivery.
        // Never promote the new target record to ZIP64 unnecessarily.
        File.Copy((string)request["input"],(string)request["output"],false);
        object archive=Activator.CreateInstance(zipType,new object[]{(string)request["output"]});
        try {
            string password=(string)request["password"];
            if(password.Length>0)zipType.GetProperty("Password").SetValue(archive,password,null);
            zipType.GetProperty("UseZip64").SetValue(archive,Enum.Parse(zip64Type,"Off"),null);
            object entry=((IEnumerable)archive).Cast<object>().SingleOrDefault(
                e=>((string)Get(e,"Name")).Replace('\\','/')=="SolutionFile/MoudleFrame");
            if(entry==null)throw new Exception("Module frame entry missing.");
            Call(archive,"BeginUpdate");
            try {
                object source=Activator.CreateInstance(sourceType,new object[]{(string)request["frame"]});
                Call(archive,"Add",source,(string)Get(entry,"Name"),Get(entry,"CompressionMethod"),(bool)Get(entry,"IsUnicodeText"));
                Call(archive,"CommitUpdate");
            } catch {
                try{Call(archive,"AbortUpdate");}catch{}
                throw;
            }
        } finally {((IDisposable)archive).Dispose();}
        return Json.Serialize(new{ok=true,packaged=true});
    }
    static void Setup(string directory) {
        apps=directory;
        foreach(string relative in new[]{"myLibs",@"PublicFile\x64",@"Module(sp)\x64"})
            foreach(string file in Directory.GetFiles(Path.Combine(apps,relative),"*.dll",SearchOption.AllDirectories)) {
                string name=Path.GetFileNameWithoutExtension(file); if (!libs.ContainsKey(name)) libs[name]=file;
            }
        AppDomain.CurrentDomain.AssemblyResolve+=(sender,e)=>{string file;return libs.TryGetValue(new AssemblyName(e.Name).Name,out file)?Assembly.LoadFrom(file):null;};
        Environment.SetEnvironmentVariable("PATH",apps+";"+string.Join(";",libs.Values.Select(Path.GetDirectoryName).Distinct())+";"+Environment.GetEnvironmentVariable("PATH"));
        Directory.SetCurrentDirectory(apps);
    }
    static object Container(object module,string side) {
        Assembly.LoadFrom(Path.Combine(apps,@"3rdLib\ICSharpCode\ICSharpCode.AvalonEdit.dll"));
        Type type=Assembly.LoadFrom(libs["ShellModuleControl"]).GetType("Apps.XmlParser.ParamTab.ShellModuleDynamicIO",true);
        return Activator.CreateInstance(type,new object[]{side,new OwnerAdapter{Owner=module}});
    }
    static void Ports(object module,Dictionary<string,object> request,bool add) {
        foreach(string side in new[]{"Input","Output"}) {
            object container=Container(module,side);
            var existing=((IEnumerable)Get(module,side=="Input"?"Inputs":"Outputs")).Cast<object>()
                .Where(p=>((string)Get(p,"Name")).StartsWith("%")).ToDictionary(p=>((string)Get(p,"Name")).Trim('%'));
            foreach(Dictionary<string,object> port in (IEnumerable)request[side=="Input"?"inputs":"outputs"]) {
                string name=(string)port["name"],kind=(string)port["type"];object io;
                if(existing.TryGetValue(name,out io)) {
                    if((string)Get(io,"TypeName")!=kind) throw new Exception("Port type conflict: "+name);
                } else if(add) {
                    // VM stores custom port identifiers with both percent markers.
                    // A bare AddIO name stays bare in VmIO.Name and is consequently
                    // absent from native AddInputParam/AddOutputParam registration.
                    Call(container,"AddIO","%"+name+"%",kind,-1);
                    object added=((IEnumerable)Get(module,side=="Input"?"Inputs":"Outputs")).Cast<object>()
                        .SingleOrDefault(p=>(string)Get(p,"Name")=="%"+name+"%");
                    if(added==null || (string)Get(added,"TypeName")!=kind)
                        throw new Exception("Native port creation failed: "+name);
                    existing[name]=added;
                }
                else throw new Exception("Port missing after reload: "+name);
            }
        }
    }
    static string Compile(object module,object manager,uint id,string source) {
        // Same registration format as VM's ShellModuleControl.SetIOParams.
        foreach(string side in new[]{"Inputs","Outputs"}) {
            object container=Container(module,side=="Inputs"?"Input":"Output");
            var displayTypes=new Dictionary<string,string>();
            foreach(object item in (IEnumerable)Get(container,"ItemsA")) {
                object io=Get(item,"IoDataSource");
                if(io!=null) displayTypes[(string)Get(io,"Name")]=(string)Get(item,"DisplayValueTypeA");
            }
            var buffer=new StringBuilder();
            foreach(object io in (IEnumerable)Get(module,side)) {
                string name=(string)Get(io,"Name");if(!name.StartsWith("%"))continue;
                string kind; if(!displayTypes.TryGetValue(name,out kind)||string.IsNullOrEmpty(kind))kind=(string)Get(io,"TypeName");
                buffer.Append(name).Append(':').Append(kind).Append(':')
                    .Append(string.Join("\r",Leaves(new[]{io}).Select(p=>(string)Get(p,"Name")))).Append('\n');
            }
            Binary(module,side=="Inputs"?"AddInputParam":"AddOutputParam",Encoding.UTF8.GetBytes(buffer.ToString()+"\0"));
        }
        Binary(module,"SetShellContent",Encoding.UTF8.GetBytes(source));
        MethodInfo method=manager.GetType().GetMethods().Single(m=>m.Name=="GetBinaryData" && m.GetParameters().Length==4 && m.GetParameters()[2].ParameterType==typeof(byte[]).MakeByRefType());
        for(int attempt=0;attempt<40;attempt++) {
            Thread.Sleep(500);object[] args={id,"CompileResult",null,3000u};method.Invoke(manager,args);
            byte[] bytes=args[2] as byte[];if(bytes==null||bytes.Length<4)continue;
            string text=Encoding.UTF8.GetString(bytes).TrimEnd('\0');
            if(text.Contains("Compile complete --")) {
                if(!System.Text.RegularExpressions.Regex.IsMatch(text,@"Compile complete --\s*0\s+Errors"))throw new Exception("VM compile failed: "+text);
                return text;
            }
        }
        throw new Exception("VM compile result timed out.");
    }
    public string Execute(string requestText) {
        var request=Json.Deserialize<Dictionary<string,object>>(requestText);requestText=null;
        Setup((string)request["apps"]);object solution=null;
        try {
            if((string)request["action"]=="package")return Package(request);
            Type st=Assembly.LoadFrom(libs["VM.Core"]).GetType("VM.Core.VmSolution",true);
            Static(st,"Load",(string)request["input"],(string)request["password"],false);
            solution=st.GetProperty("Instance").GetValue(null,null);
            if((bool)Get(solution,"IsRunning"))throw new Exception("Solution is running; application refused.");
            uint id=Convert.ToUInt32(request["module_id"]);
            object module=FindModule(solution,id);
            if(module==null)throw new Exception("Target script module could not be loaded: "+id);
            if((string)Get(module,"StrModuleName")!="ShellModule")throw new Exception("Target is not a script module.");
            Type mt=Assembly.LoadFrom(libs["VM.PlatformSDKCS"]).GetType("VM.PlatformSDKCS.ServerSDKManager",true);
            object manager=mt.GetField("mModuleManager").GetValue(mt.GetProperty("serverSDKManager").GetValue(null,null));
            bool write=(string)request["action"]=="apply";
            Ports(module,request,write);
            string compile="reload-only";
            if(write) {
                string temporary=Path.Combine((string)request["work"],"import.cs");
                File.WriteAllText(temporary,(string)request["source"],new UTF8Encoding(true));
                Call(manager,"SetParamValue",id,"ShellContent",temporary,true);
                compile=Compile(module,manager,id,(string)request["source"]);
            }
            if((bool)Get(solution,"IsRunning"))throw new Exception("Unexpected execution state.");
            Static(st,"SaveAs",(string)request["output"],(string)request["password"]);
            return Json.Serialize(new{ok=true,module_id=id,compile=compile,flows_run=false});
        } finally {
            request["password"]=null;
            if(solution!=null) ((IDisposable)solution).Dispose();
        }
    }
    [STAThread] public static int Main() {
        Console.InputEncoding=Encoding.UTF8;Console.OutputEncoding=new UTF8Encoding(false);
        bool created;using(var mutex=new Mutex(true,@"Local\VTStudioSolApply",out created)) {
            if(!created){Console.WriteLine("VT_RESULT:{\"ok\":false,\"error\":\"Another VM application task is active.\"}");return 1;}
            try {
                string request=Console.ReadLine();var data=Json.Deserialize<Dictionary<string,object>>(request);
                string directory=(string)data["apps"];data=null;
                var setup=new AppDomainSetup{ApplicationBase=directory,PrivateBinPath=@"myLibs;PublicFile\x64"};
                var domain=AppDomain.CreateDomain("VT script apply",null,setup);
                var worker=(SolScriptHost)domain.CreateInstanceFromAndUnwrap(Assembly.GetExecutingAssembly().Location,typeof(SolScriptHost).FullName);
                string result=worker.Execute(request);request=null;
                AppDomain.Unload(domain);Console.WriteLine("VT_RESULT:"+result);return 0;
            } catch(Exception ex) {
                Console.WriteLine("VT_RESULT:"+Json.Serialize(new{ok=false,error=ex.GetBaseException().Message,detail=ex.GetBaseException().StackTrace}));return 1;
            }
        }
    }
}
