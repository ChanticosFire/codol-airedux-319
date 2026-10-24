// Process-specific, temporary WFP network isolation for a suspended diagnostic child.
// The guard owns the kill-on-close job. It kills the child before closing the
// dynamic WFP session, and exits with its child or an explicit done marker (optional diagnostic bound).
// No firewall profile, adapter, service, or persistent filter is changed.
#include <windows.h>
#include <fwpmu.h>
#include <rpc.h>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <stdexcept>
#define FWPM_SESSION_FLAG_DYNAMIC 1
static const GUID FWPM_CONDITION_ALE_APP_ID={0xd78e1e87,0x8644,0x4ea5,{0x94,0x37,0xd8,0x09,0xec,0xef,0xc9,0x71}};
static const GUID FWPM_CONDITION_IP_REMOTE_ADDRESS={0xb235ae9a,0x1d64,0x49b8,{0xa4,0x4c,0x5f,0xf3,0xd9,0x09,0x50,0x45}};
static const GUID FWPM_CONDITION_IP_REMOTE_PORT={0xc35a604d,0xd22b,0x4e1a,{0x91,0xb4,0x68,0xf6,0x74,0xee,0x67,0x4b}};
static const GUID FWPM_CONDITION_IP_PROTOCOL={0x3971ef2b,0x623e,0x4f9a,{0x8c,0xb1,0x6e,0x79,0xb8,0x06,0xb9,0xa7}};
static const GUID FWPM_LAYER_ALE_AUTH_CONNECT_V4={0xc38d57d1,0x05a7,0x4c33,{0x90,0x4f,0x7f,0xbc,0xee,0xe6,0x0e,0x82}};
static const GUID FWPM_LAYER_ALE_AUTH_CONNECT_V6={0x4a72393b,0x319f,0x44bc,{0x84,0xc3,0xba,0x54,0xdc,0xb3,0xb6,0xb4}};
static const GUID FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V4={0xe1cd9fe7,0xf4b5,0x4273,{0x96,0xc0,0x59,0x2e,0x48,0x7b,0x86,0x50}};
static const GUID FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V6={0xa3b42c97,0x9f04,0x4672,{0xb8,0x7e,0xce,0xe9,0xc4,0x83,0x25,0x7f}};


static void require(bool ok, const char* what) {
    if (!ok) throw std::runtime_error(std::string(what)+" win32="+std::to_string(GetLastError()));
}
static void wfp(DWORD status, const char* what) {
    if (status) throw std::runtime_error(std::string(what)+" status="+std::to_string(status));
}
static void write(const std::filesystem::path& path, const std::string& text) {
    std::ofstream file(path, std::ios::binary); file<<text; file.close();
    if (!file) throw std::runtime_error("Could not save guard state");
}
int wmain(int argc, wchar_t** argv) {
    if(argc!=4 && argc!=5) return 2;
    unsigned long boundSeconds=120;
    if(argc==5) {
        wchar_t* end=nullptr;
        boundSeconds=wcstoul(argv[4],&end,10);
        if(!end || *end || (boundSeconds!=0 && (boundSeconds<10 || boundSeconds>3660))) return 2;
    }
    const std::filesystem::path run=argv[1], target=argv[3];
    DWORD pid=std::stoul(argv[2]);
    HANDLE process=nullptr, job=nullptr, engine=nullptr;
    FWP_BYTE_BLOB* app=nullptr;
    std::vector<UINT64> ids;
    std::string failure;
    try {
        require(std::filesystem::is_directory(run) && std::filesystem::is_regular_file(target),"Input paths");
        process=OpenProcess(PROCESS_TERMINATE|PROCESS_SET_QUOTA|PROCESS_QUERY_LIMITED_INFORMATION|SYNCHRONIZE,FALSE,pid);
        require(process!=nullptr,"Open owned child");
        wchar_t image[32768];DWORD size=32768;
        require(QueryFullProcessImageNameW(process,0,image,&size)!=FALSE,"Query child image");
        require(_wcsicmp(image,target.c_str())==0,"Exact image path mismatch");
        job=CreateJobObjectW(nullptr,nullptr);require(job!=nullptr,"Create child job");
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits={};
        limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE|JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
        limits.BasicLimitInformation.ActiveProcessLimit=1;
        require(SetInformationJobObject(job,JobObjectExtendedLimitInformation,&limits,sizeof(limits))!=FALSE,"Bound child job");
        require(AssignProcessToJobObject(job,process)!=FALSE,"Assign owned child job");
        FWPM_SESSION0 session={};session.displayData.name=const_cast<wchar_t*>(L"CODOL temporary localhost match test");
        session.flags=FWPM_SESSION_FLAG_DYNAMIC;
        wfp(FwpmEngineOpen0(nullptr,RPC_C_AUTHN_WINNT,nullptr,&session,&engine),"Open WFP session");
        wfp(FwpmGetAppIdFromFileName0(target.c_str(),&app),"Get target app ID");
        GUID subKey;UuidCreate(&subKey);
        FWPM_SUBLAYER0 sub={};sub.subLayerKey=subKey;sub.weight=0xffff;
        sub.displayData.name=const_cast<wchar_t*>(L"CODOL diagnostic process only");
        wfp(FwpmSubLayerAdd0(engine,&sub,nullptr),"Add temporary sublayer");
        FWPM_FILTER_CONDITION0 condition={};condition.fieldKey=FWPM_CONDITION_ALE_APP_ID;
        condition.matchType=FWP_MATCH_EQUAL;condition.conditionValue.type=FWP_BYTE_BLOB_TYPE;
        condition.conditionValue.byteBlob=app;
        const GUID layers[]={FWPM_LAYER_ALE_AUTH_CONNECT_V4,FWPM_LAYER_ALE_AUTH_CONNECT_V6,
                             FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V4,FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V6};
        wfp(FwpmTransactionBegin0(engine,0),"Begin filters");
        // A union of deny filters: wrong address OR wrong port OR wrong
        // protocol. No permit filter overrides other firewall decisions.
        // IPv6 remains fully blocked. Both incoming and outgoing endpoints
        // must be this exact local match service.
        for(unsigned layerIndex=0;layerIndex<4;++layerIndex) {
            unsigned rules=(layerIndex==0 || layerIndex==2)?2:1;
            for(unsigned rule=0;rule<rules;++rule) {
                FWPM_FILTER_CONDITION0 conditions[2]={condition,{}};
                unsigned count=1;
                if(rules==2) {
                    auto& endpoint=conditions[1];count=2;
                    endpoint.matchType=FWP_MATCH_NOT_EQUAL;
                    if(rule==0) {
                        endpoint.fieldKey=FWPM_CONDITION_IP_REMOTE_ADDRESS;
                        endpoint.conditionValue.type=FWP_UINT32;
                        endpoint.conditionValue.uint32=0x7f000001u;
                    } else if(rule==1) {
                        endpoint.fieldKey=FWPM_CONDITION_IP_REMOTE_PORT;
                        endpoint.conditionValue.type=FWP_UINT16;
                        endpoint.conditionValue.uint16=28969;
                    } else {
                        endpoint.fieldKey=FWPM_CONDITION_IP_PROTOCOL;
                        endpoint.conditionValue.type=FWP_UINT8;
                        endpoint.conditionValue.uint8=17;
                    }
                }
                FWPM_FILTER0 filter={};filter.displayData.name=const_cast<wchar_t*>(L"CODOL local match endpoint boundary");
                filter.layerKey=layers[layerIndex];filter.subLayerKey=subKey;
                filter.weight.type=FWP_UINT8;filter.weight.uint8=15;
                filter.numFilterConditions=count;filter.filterCondition=conditions;filter.action.type=FWP_ACTION_BLOCK;
                UINT64 id=0;wfp(FwpmFilterAdd0(engine,&filter,nullptr,&id),"Add app endpoint block");ids.push_back(id);
            }
        }
        wfp(FwpmTransactionCommit0(engine),"Commit filters");
        std::string ready="{\"guard_pid\":"+std::to_string(GetCurrentProcessId())+",\"child_pid\":"+std::to_string(pid)+",\"filter_ids\":[";
        for(size_t i=0;i<ids.size();++i) ready+=(i?",":"")+std::to_string(ids[i]);
        ready+="],\"dynamic\":true,\"job_kill_on_close\":true,\"max_processes\":1,\"bound_seconds\":"+std::to_string(boundSeconds)+"}";
        ready.pop_back();ready+=",\"scope\":\"loopback-127.0.0.1:28969\"}";
        write(run/L"guard-ready.json",ready);
        const ULONGLONG deadline=GetTickCount64()+static_cast<ULONGLONG>(boundSeconds)*1000;
        while((boundSeconds==0 || GetTickCount64()<deadline) && !std::filesystem::exists(run/L"guard-done.json") && WaitForSingleObject(process,0)==WAIT_TIMEOUT) Sleep(100);
    } catch(const std::exception& e) {failure=e.what();}
    if(process && WaitForSingleObject(process,0)==WAIT_TIMEOUT) {TerminateProcess(process,0xd1a6);WaitForSingleObject(process,3000);}
    if(job) CloseHandle(job);
    if(app) FwpmFreeMemory0(reinterpret_cast<void**>(&app));
    DWORD closed=engine?FwpmEngineClose0(engine):0;
    if(process) CloseHandle(process);
    try {write(run/L"guard-result.json","{\"closed\":true,\"engine_close_status\":"+std::to_string(closed)+",\"error\":\""+failure+"\"}");}catch(...){}
    return failure.empty() && !closed ? 0 : 1;
}
