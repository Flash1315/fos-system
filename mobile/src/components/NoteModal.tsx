import React, { useRef, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { colors } from "../theme";
import { Btn, Field, Label } from "./ui";

/** Cross-platform note prompt (Alert.prompt is iOS-only). */
export function NoteModal({
  visible,
  title,
  onCancel,
  onSubmit,
  required = false,
  label,
  placeholder = "Reason",
  secureTextEntry = false,
  confirmTitle = "Confirm",
  confirmVariant = "primary",
}: {
  visible: boolean;
  title: string;
  onCancel: () => void;
  onSubmit: (note: string) => void | Promise<void>;
  required?: boolean;
  label?: string;
  placeholder?: string;
  secureTextEntry?: boolean;
  confirmTitle?: string;
  confirmVariant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submitLock = useRef(false);
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.backdrop} onPress={onCancel}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          <Text style={styles.title}>{title}</Text>
          <Label>{label || (required ? "Note (required)" : "Note (optional)")}</Label>
          <Field
            value={note}
            onChangeText={(t) => {
              setNote(t);
              setError("");
            }}
            placeholder={placeholder}
            secureTextEntry={secureTextEntry}
            autoCapitalize={secureTextEntry ? "none" : undefined}
            autoCorrect={!secureTextEntry}
            editable={!submitting}
          />
          {!!error && <Text style={styles.error}>{error}</Text>}
          <View style={styles.row}>
            <Btn title="Cancel" variant="ghost" onPress={onCancel} disabled={submitting} />
            <Btn
              title={submitting ? "…" : confirmTitle}
              variant={confirmVariant}
              disabled={submitting}
              onPress={() => {
                if (submitLock.current) return;
                const trimmed = note.trim();
                if (required && trimmed.length < 2) {
                  setError("Add a short reason (min 2 characters)");
                  return;
                }
                submitLock.current = true;
                setSubmitting(true);
                Promise.resolve(onSubmit(trimmed))
                  .catch(() => {
                    /* caller shows errors */
                  })
                  .finally(() => {
                    submitLock.current = false;
                    setSubmitting(false);
                    setNote("");
                    setError("");
                  });
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
  row: { flexDirection: "row", gap: 10, marginTop: 14, justifyContent: "flex-end" },
  error: { color: colors.danger, marginTop: 6 },
});
