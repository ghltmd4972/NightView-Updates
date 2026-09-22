package main

import "testing"

func TestAssociationOpenCommand(t *testing.T) {
	got, err := associationOpenCommand("C:\\Users\\Test User\\AppData\\Local\\NightView\\NightView.exe")
	if err != nil {
		t.Fatal(err)
	}
	want := "\"C:\\Users\\Test User\\AppData\\Local\\NightView\\NightView.exe\" \"%1\""
	if got != want {
		t.Fatalf("command=%q want=%q", got, want)
	}
	if _, err := associationOpenCommand("C:\\Bad\"Path\\NightView.exe"); err == nil {
		t.Fatal("quoted path was accepted")
	}
}

func TestUniqueAssociationAppNamesIncludesLegacyFinalInstaller(t *testing.T) {
	names := uniqueAssociationAppNames("NightViewSetup_1.6.1_Fixed.exe")
	want := map[string]bool{
		"NightViewSetup_1.6.1_Fixed.exe": true,
		"NightViewSetup_1.6.0_Final.exe": true,
		"NightViewSetup.exe":             true,
	}
	for _, name := range names {
		delete(want, name)
	}
	if len(want) != 0 {
		t.Fatalf("missing compatibility aliases: %#v", want)
	}
}
