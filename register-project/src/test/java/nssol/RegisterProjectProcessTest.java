package nssol;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import jakarta.inject.Inject;
import jakarta.inject.Named;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.kie.kogito.Model;
import org.kie.kogito.auth.SecurityPolicy;
import org.kie.kogito.process.Process;
import org.kie.kogito.process.ProcessInstance;
import org.kie.kogito.process.WorkItem;
import org.kie.kogito.services.identity.StaticIdentityProvider;

import io.quarkus.test.junit.QuarkusTest;
import nssol.model.ProjectRegistration;
import nssol.service.ProjectStore;

/**
 * Verifies the three documented paths of NSSOL Register Project (D03 Figure 1):
 * create (isUpdate=false -> save), update (isUpdate=true -> save),
 * cancel (cancel=true -> completed, no data written).
 */
@QuarkusTest
class RegisterProjectProcessTest {

    private static final SecurityPolicy USER = SecurityPolicy.of(new StaticIdentityProvider("tester"));

    @Inject
    @Named("registerProject")
    Process<? extends Model> process;

    @BeforeEach
    void clearStore() {
        ProjectStore.clear();
    }

    private ProcessInstance<? extends Model> startToForm(boolean isUpdate, ProjectRegistration registration) {
        Model model = process.createModel();
        model.update(Map.of(
                "isUpdate", isUpdate,
                "cancel", false,
                "projectRegistration", registration));
        ProcessInstance<? extends Model> instance = process.createInstance(model);
        instance.start();
        return instance;
    }

    private WorkItem formWorkItem(ProcessInstance<? extends Model> instance) {
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_ACTIVE);
        List<WorkItem> items = instance.workItems(USER);
        assertThat(items).hasSize(1);
        assertThat(items.get(0).getName()).isEqualTo("Fill Project Registration Form");
        return items.get(0);
    }

    private ProjectRegistration sampleProject() {
        ProjectRegistration p = new ProjectRegistration();
        p.setProjectName("Test Tower Construction");
        p.setStatus("In-Progress");
        p.setOrderAmountMillionYen(new BigDecimal("500"));
        p.setExpectedOrderAmount(new BigDecimal("600"));
        p.setIsActive(true);
        return p;
    }

    @Test
    void createProject_submitsAndSaves() {
        ProjectRegistration project = sampleProject();
        ProcessInstance<? extends Model> instance = startToForm(false, project);

        WorkItem form = formWorkItem(instance);
        instance.completeWorkItem(form.getId(), Map.of(
                "cancel", false,
                "projectRegistration", project), USER);

        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_COMPLETED);
        assertThat(ProjectStore.saves()).hasSize(1);
        assertThat(ProjectStore.saves().get(0).registration().getProjectName())
                .isEqualTo("Test Tower Construction");
        assertThat(ProjectStore.saves().get(0).registration().getProjectId()).isNull();
    }

    @Test
    void updateProject_submitsAndSaves() {
        ProjectRegistration existing = sampleProject();
        existing.setProjectId(42);
        ProcessInstance<? extends Model> instance = startToForm(true, existing);

        WorkItem form = formWorkItem(instance);
        instance.completeWorkItem(form.getId(), Map.of(
                "cancel", false,
                "projectRegistration", existing), USER);

        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_COMPLETED);
        assertThat(ProjectStore.saves()).hasSize(1);
        assertThat(ProjectStore.saves().get(0).registration().getProjectId()).isEqualTo(42);
    }

    @Test
    void cancel_writesNothing() {
        ProcessInstance<? extends Model> instance = startToForm(false, sampleProject());

        WorkItem form = formWorkItem(instance);
        instance.completeWorkItem(form.getId(), Map.of(
                "cancel", true,
                "projectRegistration", sampleProject()), USER);

        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_COMPLETED);
        assertThat(ProjectStore.saves()).isEmpty();
    }
}
