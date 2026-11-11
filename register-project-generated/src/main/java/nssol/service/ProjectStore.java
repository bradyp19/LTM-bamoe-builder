package nssol.service;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import jakarta.enterprise.context.ApplicationScoped;
import nssol.model.ProjectRegistration;

/**
 * TEST DOUBLE — generated. Write semantics unspecified; records calls for tests.
 */
@ApplicationScoped
public class ProjectStore {

    public record SaveCall(ProjectRegistration registration) {}

    private static final List<SaveCall> SAVES = new CopyOnWriteArrayList<>();

    public ProjectRegistration save(ProjectRegistration projectRegistration) {
        SAVES.add(new SaveCall(projectRegistration));
        return projectRegistration;
    }

    public static List<SaveCall> saves() {
        return List.copyOf(SAVES);
    }

    public static void clear() {
        SAVES.clear();
    }
}
