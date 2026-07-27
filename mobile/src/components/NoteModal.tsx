import React, { useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { colors } from "../theme";
import { Btn, Field, Label } from "./ui";

/** Cross-platform note prompt (Alert.prompt is iOS-only). */
export function NoteModal({
  visible,
  title,
  onCancel,
  onSubmit,
}: {
  visible: boolean;
  title: string;
  onCancel: () => void;
  onSubmit: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.backdrop} onPress={onCancel}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          <Text style={styles.title}>{title}</Text>
          <Label>Note (optional)</Label>
          <Field value={note} onChangeText={setNote} placeholder="Reason" />
          <View style={styles.row}>
            <Btn title="Cancel" variant="ghost" onPress={onCancel} />
            <Btn
              title="Confirm"
              onPress={() => {
                onSubmit(note);
                setNote("");
              }}
            />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "center",
    padding: 24,
  },
  sheet: {
    backgroundColor: colors.card,
    borderRadius: 16,
    padding: 16,
  },
  title: { color: colors.text, fontSize: 18, fontWeight: "700", marginBottom: 8 },
  row: { flexDirection: "row", gap: 10 },
});
