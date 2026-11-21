// Native regression: link against the built Dart VM, not a mocked type reader.
#include "pch.h"
#include "DartTypes.h"
#include "DartClass.h"
#include "DartFnBase.h"
#include "DartLoader.h"
#include <cstdio>
#include <stdexcept>

intptr_t DartFnBase::lib_base;
uint64_t DartFnBase::lib_size;

class TestTypeDb : public DartTypeDb {
public:
    explicit TestTypeDb(std::vector<DartClass*>& classes) : DartTypeDb(classes) {}
};

static void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

int main(int argc, char** argv) {
    try {
        check(argc == 2, "Expected the libapp.so path");
        auto snapshot = ElfHelper::MapLibAppSo(argv[1]);
        check(DartLoader::Load(snapshot) != nullptr, "Dart program loading failed");

        std::vector<DartClass*> classes;
        TestTypeDb db(classes);
        auto missing = dart::AbstractType::RawCast(dart::Object::null());
        auto* first = db.FindOrAdd(missing);
        check(first == db.FindOrAdd(missing), "Missing types should share a stable placeholder");
        check(first->ToString() == "<optimized-out>", "Missing metadata must be explicit");
        check(!first->IsType() && !first->IsTypeParameter(), "Missing metadata must not pretend to be a concrete type");
        bool rejected = false;
        try {
            db.FindOrAdd(dart::AbstractType::RawCast(dart::Smi::New(1)));
        } catch (const std::runtime_error& failure) {
            rejected = std::string(failure.what()).find("Invalid abstract type (class id ") != std::string::npos;
        }
        check(rejected, "Unexpected non-type objects must still fail");
        DartFnBase::SetLibBase(0x100000, 0x100);
        check(DartFnBase::IsInLib(0x100000) && DartFnBase::IsInLib(0x1000ff), "Mapped entry points must be accepted");
        check(!DartFnBase::IsInLib(0xfffff) && !DartFnBase::IsInLib(0x100100), "Out-of-range cached entry points must be rejected");
        DartLoader::Unload();
        puts("Native optimized-out type regression: PASS");
        return 0;
    } catch (const std::exception& failure) {
        fprintf(stderr, "%s\n", failure.what());
        return 1;
    }
}
